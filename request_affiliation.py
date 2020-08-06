import pandas as pd
import rdflib
from rdflib.namespace import PROV, FOAF, RDF
import requests
from json.decoder import JSONDecodeError
import urllib.parse
import re

def parse_name(auth):
    """ Return the names of a given author.
        Expects the incoming data to be in the format of CrossRef's DOI content
        negotiation API, as given by:
        <https://github.com/CrossRef/rest-api-doc/blob/master/api_format.md>"""
    full = ""
    if 'given' in auth:
        given = auth['given']
        full += given + " "
    else:
        given = ""
    if 'family' in auth:
        family = auth['family']
        full += family
    else:
        family = ""
    return given, family, full.strip()

def prune_affil_graph(graph):
    """ Remove unwanted data from the DOI subgraph.
        Syntax is `graph.remove((sub, pred, obj))`
        Replacing one of `sub`, `pred`, `obj` with `None` makes it
        a wildcard."""
    pass

def add_affils(data, graph):
    """ Use supplied JSON data to add affiliation triples to the DOI subgraph.
        Searches for the author by name, and adds affiliation data for them.
        If the author can't be identified, creates a dummy URI for them and
        marks it for review."""
    try:
        data = data.json()
    except JSONDecodeError:
        error = "doi returned bad json"
        return error
    if 'author' not in data:
        error = "no authors"
        return error

    for auth in data['author']:
        if 'affiliation' in auth and len(auth['affiliation']) > 0:
            # attempt to get author URI by their name
            given, family, full = parse_name(auth)
            if given == "":
                query = """SELECT DISTINCT ?auth WHERE {
                    { ?auth foaf:familyName ?famname . }
                    UNION { ?auth foaf:name ?fname . }
                }"""
            elif family == "":
                query = """SELECT DISTINCT ?auth WHERE {
                    { ?auth foaf:givenName ?gname . }
                    UNION { ?auth foaf:name ?fname . }
                }"""
            else:
                query = """SELECT DISTINCT ?auth WHERE {
                   { ?auth foaf:givenName ?gname ;
                           foaf:familyName ?famname . }
                   UNION { ?auth foaf:name ?fname . }
               }"""
            query_res = graph.query(query,
                                    initBindings={'gname': rdflib.Literal(given),
                                                  'famname': rdflib.Literal(family),
                                                  'fname': rdflib.Literal(full)},
                                    initNs={'foaf':FOAF})
            # confirm the query successfully identified the author
            if len(query_res) == 1:
                # syntax to get response from query, will only loop once
                for row in query_res:
                    auth_uri = row.auth
            # if the author RDF can't be uniquely identified, create a new
            # subgraph for them
            else:
                auth_uri = json_to_author(auth, graph)
            # add each affiliation to the DOI subgraph, some are split over
            # multiple JSON entries so string them together
            full_affil = ""
            for aff in auth['affiliation']:
                full_affil += aff['name'] + " "
            full_affil = re.sub(r"[\r\n]+", " ", full_affil)
            full_affil = re.sub(r"\s\s+", " ", full_affil)
            print(full_affil)
            graph.add((auth_uri, PROV.actedOnBehalfOf, rdflib.Literal(full_affil)))
    return "ok"

def json_to_author(auth, graph):
    """ Transforms author data from JSON to RDF, storing it in a graph.
        Expects the incoming data to be in the format of CrossRef's DOI content
        negotiation API, as given by:
        <https://github.com/CrossRef/rest-api-doc/blob/master/api_format.md>"""
    given, family, full = parse_name(auth)
    auth_uri = rdflib.URIRef("http://example.org/" + urllib.parse.quote(given + family))
    graph.add((auth_uri, RDF.type, FOAF.Person))

    # add names if no parts were missing
    if full != given and full != family and full != "":
        graph.add((auth_uri, FOAF.name, rdflib.Literal(full)))
    if given != "":
        graph.add((auth_uri, FOAF.givenName, rdflib.Literal(given)))
    if family != "":
        graph.add((auth_uri, FOAF.familyName, rdflib.Literal(family)))

    return auth_uri

def get_affil_from_doi(doi, headers):
    """ Return affiliation data from a doi, if available.
        Creator data obtained through content negotiation against the DOI
        is well-formed in Turtle format, but does not contain affiliated
        institution data, only creator names. Affiliated institutions can appear
        in the JSON data instead, and thus can be grafted on to the otherwise
        complete RDF data.

        Requires the user to provide """
    headers = {}
    try:
        with open("account.txt") as f:
            headers["User-Agent"] = f.read().strip()
    except FileNotFoundError:
        print("Please provide a file `account.txt` with your email as the only",
              "line, to be used in the User-Agent header for DOI requests.")
        exit(1)
    json_headers = headers.copy()
    json_headers['Accept'] = "application/vnd.citationstyles.csl+json"
    ttl_headers = headers.copy()
    ttl_headers['Accept'] = "text/turtle"

    doi_graph = rdflib.Graph()

    json_response = requests.get(doi, headers=json_headers)
    ttl_response = requests.get(doi, headers=ttl_headers)
    if ttl_response:
        # we can use the rdf data to build a scaffold for the affiliation data
        try:
            doi_graph.parse(data=ttl_response.content.decode("utf-8"), format='turtle')
        except SyntaxError:
            msg = "doi was not encoded properly"
            return msg, None
        # currently does nothing, but could remove unwanted triples from final product
        prune_affil_graph(doi_graph)
        msg = "ok"

    # if there is affiliation data to add from json, add it or append it
    if json_response:
        msg = add_affils(json_response, doi_graph)

    else:
        msg = "doi returned no data"
        return msg, None
    return msg, doi_graph

if __name__ == '__main__':
    headers = {'User-Agent':"mailto:rory.21@dartmouth.edu"}
    dois = pd.read_csv("queryResults.csv", header=None)
    doi_list = dois[0].to_list()
    broken = pd.DataFrame(columns=['reason','doi'])
    aff_count = 0
    totg = rdflib.Graph()
    for doi in doi_list:
        msg, affil_graph = get_affil_from_doi(doi, headers)
        if msg == "ok":
            totg += affil_graph
        else:
            broken = broken.append({'reason':msg, 'doi':doi}, ignore_index=True)
    totg.serialize("test.ttl", format="turtle")
    broken.to_csv("broken.csv", index=False)

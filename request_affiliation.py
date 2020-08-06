import pandas as pd
import rdflib
from rdflib.namespace import PROV, FOAF, RDF
import requests
from json.decoder import JSONDecodeError
import urllib.parse

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
        if 'affiliation' in auth:
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
                # add each affiliation to the DOI subgraph
                for aff in auth['affiliation']:
                    graph.add((auth_uri, PROV.actedOnBehalfOf, rdflib.Literal(aff['name'])))
            # if the author RDF can't be found, create a new subgraph for them
            else:
                auth_uri = json_to_author(auth, graph)
    return "ok"

def json_to_author(auth, graph):
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

    if 'affiliation' in auth:
        for aff in auth['affiliation']:
            graph.add((auth_uri, PROV.actedOnBehalfOf, rdflib.Literal(aff['name'])))

    return auth_uri

def get_affil_from_doi(doi, headers):
    """ Return affiliation data from a doi, if available.
        Creator data is well-formed in Turtle format, but does
        not contain affiliated institution data, only names.
        Affiliated institutions can appear in the JSON data instead"""
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

        # if there is affiliation data to add from json, add it. else, we're done
        if json_response:
            msg = add_affils(json_response, doi_graph)
        else:
            msg = "ok"

    # if there's no rdf data, then simply use json if it's available
    elif json_response:
        try:
            data = json_response.json()
        except JSONDecodeError:
            msg = "doi returned bad json"
            return msg, None
        if 'author' not in data:
            msg = "no authors"
            return msg, None
        for auth in data['author']:
            auth_uri = json_to_author(auth, doi_graph)
        msg = "ok"
    else:
        msg = "doi returned no data"
        return msg, None
    return msg, doi_graph

if __name__ == '__main__':
    headers = {'User-Agent':"mailto:rory.21@dartmouth.edu"}
    dois = pd.read_csv("queryResults.csv", header=None)
    doi_list = dois[0].to_list()
    broken = pd.DataFrame(columns=['reason','doi'])
    source = pd.DataFrame(columns=['source','doi'])
    aff_count = 0
    totg = rdflib.Graph()
    for doi in doi_list:
        msg, affil_graph = get_affil_from_doi(doi, headers)
        if msg == "ok":
            totg += affil_graph
        else:
            broken = broken.append({'reason':msg, 'doi':doi}, ignore_index=True)
    source.to_csv("sources.csv")
    totg.serialize("test.ttl", format="turtle")

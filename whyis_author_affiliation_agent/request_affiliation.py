import rdflib
from rdflib.namespace import PROV, FOAF, RDF, DCTERMS, Namespace
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")

import requests
from json.decoder import JSONDecodeError
import urllib.parse
import re

from arcgis.gis import GIS
from arcgis.geocoding import geocode

# Load the user's email, to be used for making content negotiation requests
USER_AGENT = ""
try:
    with open("useragent.txt") as f:
        USER_AGENT = f.read().strip()
except FileNotFoundError:
    msg = ("Please provide a file `useragent.txt` with your email as the only"
          "line, to be used in the User-Agent header for DOI requests.")
    raise FileNotFoundError(msg) from FileNotFoundError

# Load the user's ArcGIS account information, to be used when requesting
# location data. Replace with alternate code if not using the application
# client ID
GIS_CLIENT = None
try:
    with open("arcgisclient.txt") as f:
        GIS_CLIENT = f.read().strip()
except FileNotFoundError:
    msg = ("Please provide a file `arcgisclient.txt` with your ArcGIS application "
          "client ID, to be used to log in to ArcGIS. If none is provided, the "
          "agent may be unable to retrieve latitude/longitude data for affiliations.")
    raise FileNotFoundError(msg) from FileNotFoundError
if GIS_CLIENT is not None and GIS_CLIENT != "":
    gis = GIS(client_id=GIS_CLIENT)
else:
    gis = GIS()

def get_affil_from_doi(doi):
    """ Return affiliation data from a doi, if available.
        Creator data obtained through content negotiation against the DOI
        is well-formed in Turtle format, but does not contain affiliated
        institution data, only creator names. Affiliated institutions can appear
        in the JSON data instead, and thus can be grafted on to the otherwise
        complete RDF data."""
    headers = {"User-Agent":USER_AGENT}
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
            auth_uri = get_author_uri(auth, graph)

            # some affiliation names are split over multiple JSON entries
            affil_name = ""
            for aff_frag in auth['affiliation']:
                affil_name += aff_frag['name'] + " "

            # clean up the affiliation name
            affil_name = affil_name.strip()
            affil_name = re.sub(r"[\r\n]+", " ", affil_name)
            affil_name = re.sub(r"\s\s+", " ", affil_name)

            # retrieve affiliation coordinates, if available
            aff_lat, aff_long = get_affiliation_coords(affil_name)

            # insert affiliation subgraph
            affiliation = rdflib.BNode()
            graph.add((affiliation, FOAF.name, rdflib.Literal(affil_name)))
            if aff_lat is not None and aff_long is not None:
                graph.add((affiliation, GEO.lat, rdflib.Literal(aff_lat)))
                graph.add((affiliation, GEO.long, rdflib.Literal(aff_long)))

            # attach affiliation subgraph to author, DOI
            graph.add((auth_uri, PROV.actedOnBehalfOf, affiliation))
            graph.add((rdflib.URIRef(doi), DCTERMS.contributor, affiliation))
    return "ok"

def get_author_uri(auth, graph):
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

    return auth_uri

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

def get_affiliation_coords(location_name, score_limit=70):
    """ Return the latitude and longitude of a location.
        Only returns the coordinates if the geocoder returns a score of at least
        score_limit. Returns a tuple (latitude, longitude). Requires an ArcGIS
        application, see <https://developers.arcgis.com/python/>"""
    if len(location_name) > 200:
        location_name = location_name[-200:]
    res = geocode(address=location_name, max_locations=1)[0]
    if res['score'] < score_limit:
        return None, None
    else:
        lat = res['location']['y']
        long = res['location']['x']
        return lat, long

def prune_affil_graph(graph):
    """ Remove unwanted data from the DOI subgraph.
        Syntax is `graph.remove((sub, pred, obj))`
        Replacing one of `sub`, `pred`, `obj` with `None` makes it
        a wildcard."""
    pass

if __name__ == '__main__':
    import pandas as pd
    dois = pd.read_csv("queryResults.csv", header=None)
    doi_list = dois[0].to_list()
    broken = pd.DataFrame(columns=['reason','doi'])
    aff_count = 0
    totg = rdflib.Graph()
    for doi in doi_list:
        msg, affil_graph = get_affil_from_doi(doi)
        if msg == "ok":
            totg += affil_graph
        else:
            broken = broken.append({'reason':msg, 'doi':doi}, ignore_index=True)
    totg.serialize("loctest.ttl", format="turtle")
    broken.to_csv("broken.csv", index=False)

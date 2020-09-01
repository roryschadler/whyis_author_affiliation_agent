""" Provides a testing framework for the Author Affiliation Agent."""

from rdflib import *
import math

from whyis_author_affiliation_agent import affiliation_agent as auth_aff

from whyis import nanopub
from whyis.namespace import dc, foaf, prov
from whyis.test.agent_unit_test_case import AgentUnitTestCase

geo = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")

class AuthorAfiliationAgentTestCase(AgentUnitTestCase):
    def test_affiliation_retrieval(self):
        np = nanopub.Nanopublication()
        np.assertion.parse(data='''{
        "@id": "http://dx.doi.org/10.1002/app.44347",
        "@type": [ "http://purl.org/dc/terms/BibliographicResource" ]
        }''', format="json-ld")
        # print(np.serialize(format="trig"))
        agent = auth_aff.AffiliationAgent()
        results = self.run_agent(agent, nanopublication=np)

        self.assertEquals(len(results), 1)
        # print("Printing agent results:\n\n", results[0].serialize(format="trig"), "\n")

        contains_LS = False
        found_RPI = False
        lat_correct = False
        long_correct = False
        if len(results) > 0:
            for auth in results[0].resource(URIRef("http://dx.doi.org/10.1002/app.44347"))[dc.creator]:
                if auth[foaf.familyName : Literal("Schadler")]:
                    contains_LS = True
                    rpi = Literal("Department of Materials Science and Engineering; Rensselaer Polytechnic Institute; 110 8th Street MRC 140 Troy New York 12180")
                    for aff in auth[prov.actedOnBehalfOf]:
                        if aff[foaf.name : rpi]:
                            found_RPI = True
                            for lati in aff[geo.lat]:
                                if math.isclose(lati.value, 42.73119):
                                    lat_correct = True
                            for longi in aff[geo.long]:
                                if math.isclose(longi.value, -73.6832):
                                    long_correct = True

        self.assertTrue(contains_LS)
        self.assertTrue(found_RPI)
        self.assertTrue(lat_correct)
        self.assertTrue(long_correct)

    def test_bad_doi(self):
        np = nanopub.Nanopublication()
        np.assertion.parse(data='''{
        "@id": "http://example.com/NotADOI",
        "@type": [ "http://purl.org/dc/terms/BibliographicResource" ]
        }''', format="json-ld")
        # print(np.serialize(format="trig"))
        agent = auth_aff.AffiliationAgent()
        results = self.run_agent(agent, nanopublication=np)

        self.assertEquals(len(results), 0)

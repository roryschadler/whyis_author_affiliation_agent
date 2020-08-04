""" Author affiliation location Agent for Whyis
    Uses <http://tetherless-world.github.io/whyis/inference>
    as a template.
"""

from __future__ import division
from past.utils import old_div
import nltk, re, pprint
from rdflib import *
from rdflib.resource import Resource
from time import time

from whyis import autonomic
from whyis import nanopub
from whyis.namespace import sioc_types, sioc, sio, dc, prov, whyis

class AffiliationAgent(autonomic.GlobalChangeService):
    activity_class = whyis.AffiliationAgent

    def getInputClass(self):
        return sio.Entity

    def getOutputClass(self):
        return sio.Entity

    def get_query(self):
        query = '''SELECT ?s WHERE {
    ?s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://purl.org/dc/terms/BibliographicResource> .
}'''
        return query

    def process(self, i, o):
        pass

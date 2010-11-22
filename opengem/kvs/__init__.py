# -*- coding: utf-8 -*-
"""
This module contains generic functions to access
the underlying kvs systems.
"""

import json
import logging
import uuid
from opengem.kvs.redis import Redis

logging.getLogger('jpype').setLevel(logging.ERROR)

DEFAULT_LENGTH_RANDOM_ID = 8
INTERNAL_ID_SEPARATOR = ':'
MAX_LENGTH_RANDOM_ID = 36
MEMCACHE_KEY_SEPARATOR = '!'


def generate_job_key(job_id):
    """ Return a job key """
    return _generate_key(("JOB", str(job_id)))


def generate_sites_key(job_id, block_id):
    """ Return sites key """

    sites_key_token = 'sites'
    return generate_product_key(job_id, sites_key_token, block_id)


def generate_product_key(job_id, product, block_id="", site=""):
    """construct memcached key from several part IDs"""
    # TODO(chris): FIXME modify below to always have 4 fields in the key.

    strip = lambda x: x.replace(" ", "")
    key_list = [str(job_id), str(block_id),
            strip(str(site)), strip(str(product))]

    return _generate_key(key_list)


def generate_random_id(length=DEFAULT_LENGTH_RANDOM_ID):
    """This function returns a random ID by using the uuid4 method. In order
    to have reasonably short IDs, the ID returned from uuid4() is truncated.
    This is not optimized for being collision-free. See documentation of uuid:
    http://docs.python.org/library/uuid.html
    http://en.wikipedia.org/wiki/Universally_unique_identifier
    """
    if length > MAX_LENGTH_RANDOM_ID:
        length = MAX_LENGTH_RANDOM_ID
    return str(uuid.uuid4())[0:length]

def get_client(**kwargs):
    """possible kwargs:
        binary
    """

    return Redis(**kwargs)

def get_sites_from_memcache(job_id, block_id):
    """ Get all of the sites for a block """

    memcache_key_sites = generate_sites_key(job_id, block_id)
    return get_value_json_decoded(memcache_key_sites)


def get_value_json_decoded(key):
    """ Get value from kvs and json decode """
    try:
        value = get_client(binary=False).get(key)
        decoder = json.JSONDecoder()
        return decoder.decode(value)
    except Exception, e:
        print "Key was %s" % key
        print e
        print "Raw JSON was: %s" % value
        return None


def set_value_json_encoded(key, value):
    """ Encode value and set in kvs """
    encoder = json.JSONEncoder()

    try:
        encoded_value = encoder.encode(value)
    except Exception:
        raise ValueError("cannot encode value %s to JSON" % value)

    try:
        get_client(binary=False).set(key, encoded_value)
    except Exception, e:
        raise RuntimeError("cannot write key %s to memcache - %s" % (key, e))

    return True


def set(key, encoded_value):
    """ Set value in kvs, for objects that have their own encoding method. """
    try:
        get_client(binary=False).set(key, encoded_value)
    except Exception, e:
        raise RuntimeError("cannot write key %s to memcache - %s" % (key, e))
    return True


def _generate_key(key_list):
    """ Create a kvs key """
    return MEMCACHE_KEY_SEPARATOR.join(key_list)


def _prefix_id_generator(prefix):
    """Generator for IDs with a specific prefix (prefix + sequence number)."""

    counter = 0
    while(True):
        counter += 1
        yield INTERNAL_ID_SEPARATOR.join((str(prefix), str(counter)))

# generator instance used to generate IDs for blocks
BLOCK_ID_GENERATOR = _prefix_id_generator("block")

def generate_block_id():
    """Generate a unique id for a block."""
    return BLOCK_ID_GENERATOR.next()

def generate_vuln_key(job_id):
    """Generate the key used to store vulnerability curves."""
    return generate_product_key(job_id, "vulnerability_curves")

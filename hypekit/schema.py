"""JSON Schema of the records hypekit returns (the contract for agents and other tools). Bump VERSION on changes."""

VERSION = 1

_S, _I, _N, _B = {'type': 'string'}, {'type': 'integer'}, {'type': ['number', 'null']}, {'type': 'boolean'}
_LS = {'type': 'array', 'items': _S}

RECORDS = {
    'sound': {
        'description': "A playable sound: bank entry, .apm stream or track (several entries played in order). "
                       "Payload: wav(id).",
        'properties': {
            'id': {**_S, 'description': "'Bnk_<n>:<node>' or 'apm:<file>'"},
            'kind': {'enum': ['voice', 'music', 'music part', 'sfx', 'ambience', 'unused']},
            'title': {**_S, 'description': 'readable name (speaker: line for voices)'},
            'bank': _S, 'node': _S, 'file_name': {**_S, 'description': 'name inside the bank / stream file'},
            'format': {'enum': ['PCM', 'APM', 'MPEG', 'APM stream', 'Track']},
            'seconds': {**_N, 'description': 'null until an MPEG bank was decoded once'},
            'rate': _I, 'channels': _I, 'size': _I, 'volume': _I, 'loop': _I,
            'loop_start': {**_N, 'description': 'tracks: seconds where the loop restarts'},
            'levels': {**_LS, 'description': "levels that use it ('Fix' = everywhere)"},
            'group_name': {**_S, 'description': 'sound designer group (.csb, needs disc copies)'},
            'speaker': _S, 'dialog': {**_S, 'description': 'dialogue sequence name, joins lines.dialog'},
            'text': _S, 'part': _S, 'parts': {**_LS, 'description': 'track part sound ids'},
        },
    },
    'line': {
        'description': 'One dialogue turn from a level .lng, in the install language.',
        'properties': {
            'id': {**_S, 'description': "'<level>:<n>'"}, 'level': _S, 'n': _I,
            'dialog': _S, 'speaker': {**_S, 'description': "as in the game, e.g. 'RAJOTH'"}, 'text': _S,
            'common': {**_B, 'description': 'in more than two levels (pickup / menu text)'},
        },
    },
    'texture': {
        'description': 'One texture of Textures.cnt / Vignette.cnt. Payload: png(id), always upright.',
        'properties': {
            'id': {**_S, 'description': "'<archive>:<index>'"}, 'archive': {'enum': ['Textures', 'Vignette']},
            'idx': _I, 'path': _S, 'size': _I, 'width': _I, 'height': _I,
            'format': {'enum': ['pal8', 'rgb565', 'argb1555', 'argb4444', '']}, 'mips': _I, 'error': _S,
        },
    },
    'save': {
        'description': 'One save slot, decoded (read-only). Item and spell names are in the install language.',
        'properties': {
            'id': {**_S, 'description': "slot folder, e.g. 'SaveGame3'"}, 'level': _S, 'place': _S,
            'checkpoint': _S, 'playtime': {**_I, 'description': 'seconds'}, 'modified': {**_I, 'description': 'unix time'},
            'debug': _B, 'health': _I, 'health_max': _I, 'health_maxmax': _I, 'mana': _I, 'mana_max': _I,
            'gold': _I, 'gold_max': _I, 'eras': {'type': 'array', 'items': _I}, 'map_destinations': {'type': 'array', 'items': _I},
            'records': _I,
            'inventory': {'type': 'array', 'items': {'type': 'object', 'description': 'name, type, count, max, selected, carried'}},
            'spells': {'type': 'array', 'items': {'type': 'object', 'description': 'name, element, selected'}},
            'armour': {'type': 'array', 'items': {'type': 'object', 'description': 'n, resistance, damaged, pieces, pieces_damaged'}},
            'flags': {'type': 'array', 'items': {'type': 'object', 'description': 'Global DsgVar index, value, note'}},
        },
    },
    'perso': {
        'description': 'A character / animated figure placed in a level. Payload: glb(id, state) (glTF binary, '
                       'one node per animation channel, sprites marked extras.sprite). Records come from a one-time '
                       'background scan of all levels.',
        'properties': {
            'id': {**_S, 'description': "'<level>:<superobject hex>'"}, 'level': _S, 'so': _S,
            'name': {**_S, 'description': "instance name, e.g. 'Hype', 'I_Granslak'"}, 'family': _S,
            'states': {**_I, 'description': 'number of states (animations)'}, 'parts': _I,
            'frames': {**_I, 'description': 'frames of the initial state'}, 'fps': _I,
        },
    },
}


def json_schema(kind=None):
    def one(k):
        r = RECORDS[k]
        return {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': f'hypekit/{k}/v{VERSION}',
                'title': k, 'type': 'object', 'description': r['description'], 'properties': r['properties'],
                'required': ['id']}
    return one(kind) if kind else {k: one(k) for k in RECORDS}

from senza.utils import camel_case_to_underscore, extract_attribute


def test_camel_case_to_underscore():
    assert camel_case_to_underscore('CamelCaseToUnderscore') == 'camel_case_to_underscore'
    assert camel_case_to_underscore('ThisIsABook') == 'this_is_a_book'
    assert camel_case_to_underscore('InstanceID') == 'instance_id'


def test_extract_attribute_that_is_set():
    definition = {
        'Mappings': {
            'Senza': {
                'Info': {
                    'ApplicationName': 'SenzaApp'
                }
            }
        }
    }
    assert extract_attribute(definition, 'ApplicationName') == 'SenzaApp'


def test_extract_attribute_that_is_not_set():
    definition = {
        'Mappings': {
            'Senza': {
                'Info': {
                }
            }
        }
    }
    assert extract_attribute(definition, 'ApplicationName') is None


def test_extract_attribute_empty_definition():
    definition = {}
    assert extract_attribute(definition, 'ApplicationName') is None

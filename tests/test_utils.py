from senza.utils import camel_case_to_underscore


def test_camel_case_to_underscore():
    assert camel_case_to_underscore('CamelCaseToUnderscore') == 'camel_case_to_underscore'

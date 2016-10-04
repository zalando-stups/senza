from senza.utils import camel_case_to_underscore


def test_camel_case_to_underscore():
    assert camel_case_to_underscore('CamelCaseToUnderscore') == 'camel_case_to_underscore'
    assert camel_case_to_underscore('ThisIsABook') == 'this_is_a_book'
    assert camel_case_to_underscore('InstanceID') == 'instance_id'

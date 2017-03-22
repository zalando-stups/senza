from senza.utils import camel_case_to_underscore, get_load_balancer_name


def test_camel_case_to_underscore():
    assert camel_case_to_underscore('CamelCaseToUnderscore') == 'camel_case_to_underscore'
    assert camel_case_to_underscore('ThisIsABook') == 'this_is_a_book'
    assert camel_case_to_underscore('InstanceID') == 'instance_id'


def test_get_load_balancer_name():
    assert get_load_balancer_name(stack_name='really-long-application-name',
                                  stack_version='cd871c54') == 'really-long-application-cd871c54'
    assert get_load_balancer_name(stack_name='app-name', stack_version='1') == 'app-name-1'

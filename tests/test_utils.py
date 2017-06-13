from senza.utils import camel_case_to_underscore, get_load_balancer_name, generate_valid_cloud_name


def test_camel_case_to_underscore():
    assert camel_case_to_underscore('CamelCaseToUnderscore') == 'camel_case_to_underscore'
    assert camel_case_to_underscore('ThisIsABook') == 'this_is_a_book'
    assert camel_case_to_underscore('InstanceID') == 'instance_id'


def test_get_load_balancer_name():
    assert get_load_balancer_name(stack_name='really-long-application-name',
                                  stack_version='cd871c54') == 'really-long-application-cd871c54'
    assert get_load_balancer_name(stack_name='app-name', stack_version='1') == 'app-name-1'


def test_generate_valid_cloud_name():
    assert generate_valid_cloud_name(name='invalid-aws--cloud-name', length=32) == 'invalid-aws-cloud-name'
    assert generate_valid_cloud_name(name='-invalid-aws-cloud-name', length=32) == 'invalid-aws-cloud-name'
    assert generate_valid_cloud_name(name='invalid-aws-cloud-name-', length=32) == 'invalid-aws-cloud-name'
    assert generate_valid_cloud_name(name='invalid-aws--cloud-name-', length=32) == 'invalid-aws-cloud-name'
    assert generate_valid_cloud_name(name='invalid-aws-cloud-name-long-replaced', length=27) == 'invalid-aws-cloud-name-long'

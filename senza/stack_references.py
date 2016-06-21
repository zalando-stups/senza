def check_file_exceptions(stack_references: list):
    """
    Check all stack references to see if any references that looks like a yaml
    filename wasn't matched and raises an filerror
    """
    for stack in stack_references:
        stack.raise_file_exception()

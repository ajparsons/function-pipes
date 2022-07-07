all:
	export arg_limit=20 && export param_spec=1 && j2 src/function_pipes/pipes.jinja-py > src/function_pipes/with_paramspec/function_pipes.py
	black src/function_pipes/with_paramspec/function_pipes.py
	export arg_limit=20 && export param_spec=0 && j2 src/function_pipes/pipes.jinja-py > src/function_pipes/without_paramspec/function_pipes.py
	black src/function_pipes/without_paramspec/function_pipes.py
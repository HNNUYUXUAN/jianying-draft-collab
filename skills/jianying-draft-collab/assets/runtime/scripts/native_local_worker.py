"""Isolated worker for a reviewed device-local adapter; never invoked by projects."""
import importlib.util
import json
from pathlib import Path
import sys


def main():
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    spec=importlib.util.spec_from_file_location('local_native_adapter',request['module'])
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.execute(Path(request['app']),request['args'],cwd=request['cwd'],timeout=request['timeout'])
    if not isinstance(result,dict):
        raise TypeError('Local adapter execute() must return a normalized native result object')
    print(json.dumps({'native_local_result':result},ensure_ascii=True))


if __name__=='__main__':
    main()

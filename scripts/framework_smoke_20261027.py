import tempfile,json,sys
from pathlib import Path
from framework_bench_20261027 import Gateway,invoke,Reading,ROOT
results=[]
for framework in sys.argv[1:] or ['langgraph','dspy','pydanticai','crewai','autogen']:
    try:
        with tempfile.TemporaryDirectory(dir=ROOT/'data/qa') as d:
            g=Gateway(Path(d),True)
            result=invoke(framework,g,'输出本地测试对象',{'text':'本地模拟，不调用模型'},Reading)
            Reading.model_validate(result)
            if g.calls!=1:raise ValueError('expected_single_transport_call')
            record={'framework':framework,'ok':True,'calls':g.calls}
    except Exception as exc:record={'framework':framework,'ok':False,'error':type(exc).__name__+':'+str(exc)[:500]}
    results.append(record);print(json.dumps(record),flush=True)

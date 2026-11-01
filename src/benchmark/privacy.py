"""Mask actual credential values without destroying public JSON tool schemas."""
import json
import re

SENSITIVE={"password","new_password","api_key","secret","token","authorization"}


class Mask:
    def __init__(self,secrets=()):self.secrets=set(filter(None,secrets))

    def learn(self,value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.lower() in SENSITIVE and isinstance(item,str) and item:self.secrets.add(item)
                else:self.learn(item)
        elif isinstance(value,(list,tuple)):
            for item in value:self.learn(item)

    def __call__(self,value):
        if hasattr(value,"model_dump"):value=value.model_dump(mode="json")
        if isinstance(value,dict):
            return {key:"[WITHHELD]" if key.lower() in SENSITIVE and not isinstance(item,(dict,list))
                else self(item) for key,item in value.items()}
        if isinstance(value,(list,tuple)):return [self(item) for item in value]
        if isinstance(value,str):
            for secret in sorted(self.secrets,key=len,reverse=True):value=value.replace(secret,"[WITHHELD]")
            if value.lstrip().startswith(("{","[")):
                try:return json.dumps(self(json.loads(value)),ensure_ascii=False)
                except (ValueError,RecursionError):pass
            value=re.sub(r'(?i)(\b(?:password|new_password|api_key|secret|token|authorization)\b["\x27]?\s*[:=]\s*)("(?:\\.|[^"\\])*"|\x27[^\x27]*\x27|[^\s,;}\]]+)',r'\1[WITHHELD]',value)
        return value

    def span_processor(self,span):
        if span.inputs is not None:span.set_inputs(self(span.inputs))
        if span.outputs is not None:span.set_outputs(self(span.outputs))
        for key,value in list(span.attributes.items()):
            if key not in {"mlflow.spanInputs","mlflow.spanOutputs"}:span.set_attribute(key,self(value))
        if span.status.description:
            from mlflow.entities import SpanStatus
            span.set_status(SpanStatus(span.status.status_code,self(span.status.description)))
        # MLflow's processor API has no event mutation method. The locked OTel
        # Event exposes immutable public attributes backed by _attributes; mask
        # that backing mapping before export and never export raw stack traces.
        for event in span._span.events:
            event._attributes={key:"[WITHHELD]" if key=="exception.stacktrace" else self(value)
                for key,value in (event.attributes or {}).items()}

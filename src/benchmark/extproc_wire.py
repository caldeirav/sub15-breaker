"""Header-only subset of Envoy ext_proc v3, not a general Envoy SDK.

Field numbers/types match envoy/service/ext_proc/v3/external_processor.proto,
envoy/config/core/v3/base.proto and envoy/type/v3/http_status.proto. Unknown
protobuf fields are ignored; unsupported processing phases fail closed. Tests
pin bytes produced by upstream xds-protos 1.85.1. Avoid that package at runtime:
it installs conflicting OpenTelemetry protobuf modules and breaks MLflow.
"""
import grpc
from google.protobuf import descriptor_pb2,descriptor_pool,message_factory

PACKAGE="breaker.benchmark.extproc"
file=descriptor_pb2.FileDescriptorProto(name="breaker_benchmark_extproc.proto",package=PACKAGE,syntax="proto3")


def message(name,fields,oneof=None):
    definition=file.message_type.add(name=name)
    if oneof:definition.oneof_decl.add(name=oneof)
    for name,number,type_name,repeated in fields:
        field=definition.field.add(name=name,number=number,label=3 if repeated else 1)
        if type_name in {"string","bytes","int32"}:field.type={"string":9,"bytes":12,"int32":5}[type_name]
        else:field.type=11;field.type_name="."+PACKAGE+"."+type_name
        if oneof:field.oneof_index=0


message("HeaderValue",[("key",1,"string",False),("value",2,"string",False),("raw_value",3,"bytes",False)])
message("HeaderMap",[("headers",1,"HeaderValue",True)])
message("HttpHeaders",[("headers",1,"HeaderMap",False)])
message("HeadersResponse",[])
message("HttpStatus",[("code",1,"int32",False)])
message("ImmediateResponse",[("status",1,"HttpStatus",False),("body",3,"bytes",False),("details",5,"string",False)])
message("ProcessingRequest",[("request_headers",2,"HttpHeaders",False)],"request")
message("ProcessingResponse",[("request_headers",1,"HeadersResponse",False),("immediate_response",7,"ImmediateResponse",False)],"response")
pool=descriptor_pool.DescriptorPool();pool.Add(file)
ProcessingRequest=message_factory.GetMessageClass(pool.FindMessageTypeByName(PACKAGE+".ProcessingRequest"))
ProcessingResponse=message_factory.GetMessageClass(pool.FindMessageTypeByName(PACKAGE+".ProcessingResponse"))
HeadersResponse=message_factory.GetMessageClass(pool.FindMessageTypeByName(PACKAGE+".HeadersResponse"))
ImmediateResponse=message_factory.GetMessageClass(pool.FindMessageTypeByName(PACKAGE+".ImmediateResponse"))


def add_processor(processor,server):
    handler=grpc.stream_stream_rpc_method_handler(processor.Process,
        request_deserializer=ProcessingRequest.FromString,response_serializer=ProcessingResponse.SerializeToString)
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(
        "envoy.service.ext_proc.v3.ExternalProcessor",{"Process":handler}),))

#!/usr/bin/env sh
pushd protobuf > /dev/null
protoc --cpp_out=../node/source --python_out=../server delegate.proto
popd > /dev/null

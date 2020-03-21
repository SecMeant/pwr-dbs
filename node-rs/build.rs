extern crate protoc_rust;

use protoc_rust::Customize;

fn main() {
    protoc_rust::run(protoc_rust::Args {
        out_dir: "src/protos",
        input: &["../protobuf/delegate.proto"],
        includes: &["src/protos", "../protobuf"],
        customize: Customize {
            ..Default::default()
        },
    })
    .expect("protoc");
}

mod protos;
use protobuf::{parse_from_bytes, Message};
use protos::delegate::*;

extern crate websocket;

use std::env;
use websocket::client::ClientBuilder;
use websocket::dataframe::DataFrame;

type Websock = websocket::sync::Client<std::net::TcpStream>;

fn usage(program_name: &String) {
    println!("Usage: {} <host> <port> <resource>", program_name);
}

fn recv_protobuf<T : Message>(ws: &mut Websock) -> T {
    let indata = ws.recv_dataframe().unwrap().data;
    println!("Got data: {:?}", indata);

    parse_from_bytes::<T>(&indata).unwrap()
}

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() != 4 {
        usage(&args[0]);
        std::process::exit(1);
    }

    let host = &args[1];
    let port = &args[2];
    let resource = &args[3];
    let url = format!("ws://{}:{}{}", host, port, resource);

    let mut ws = ClientBuilder::new(&url)
        .unwrap()
        .add_protocol("rust-websocket")
        .connect_insecure()
        .unwrap();

    println!("Connected to {}", url);

    let mut register_request = RegisterNodeRequest::default();
    register_request.set_version(1);
    let outdata = websocket::Message::binary(register_request.write_to_bytes().unwrap());
    ws.send_message(&outdata).unwrap();

    // For some reason first read is not blocking (?)
    // To restore blocking behavior simply read once and expect to fail.
    // TODO(holz) obv check why it returns empty slice.
    let d = ws.recv_dataframe().unwrap().data;
    if !d.is_empty() {
        panic!("Expected first read to fail.");
    }

    let register_response = recv_protobuf::<RegisterNodeResponse>(&mut ws);

    match register_response.get_code() {
        0 => { println!("Node registered"); },
        _ => { panic!("Node registration failed"); }
    }

}

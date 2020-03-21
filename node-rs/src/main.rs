mod protos;
use protobuf::{parse_from_bytes, Message};
use protos::delegate::*;

extern crate websocket;

use std::env;
use std::fmt;
use websocket::client::ClientBuilder;

fn usage(program_name: &String) {
    println!("Usage: {} <host> <port> <resource>", program_name);
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

    let client = ClientBuilder::new(&url)
        .unwrap()
        .add_protocol("rust-websocket")
        .connect_insecure()
        .unwrap();

    println!("Connected to {}", url);
}

mod protos;
use protobuf::{parse_from_bytes, Message};
use protos::delegate::*;

extern crate websocket;

use std::env;
use std::env::current_dir;
use std::env::set_current_dir;
use std::path::Path;
use std::path::PathBuf;
use std::fs::metadata;
use std::fs::create_dir_all;
use std::process::Command;

use websocket::client::ClientBuilder;
use websocket::dataframe::DataFrame;

type Websock = websocket::sync::Client<std::net::TcpStream>;

const ENV : &str = "/usr/bin/env";

fn usage(program_name: &String) {
    println!("Usage: {} <host> <port> <resource>", program_name);
}

fn recv_protobuf<T : Message>(ws: &mut Websock) -> T {
    let mut dataframe = ws.recv_dataframe().unwrap();

    while dataframe.data.is_empty() {
        dataframe = ws.recv_dataframe().unwrap();
    }

    parse_from_bytes::<T>(&dataframe.data).unwrap()
}

fn repo_outdir(name : &str, rev : &str) -> PathBuf {
    Path::new(name).join(rev)
}

fn repo_ready(outdir: &str) -> bool {
    match metadata(outdir) {
        Ok(md) => md.is_dir(),
        Err(_) => false,
    }
}

fn repo_clone(url: &str, outdir: &str, rev: &str) -> BootstrapResponse_Code {
    println!("Cloning {} into {} (rev {})", url, outdir, rev);

    if repo_ready(outdir) {
        println!("{} already exists at {}. Using existing instead.", url, outdir);
        return BootstrapResponse_Code::OK;
    }

    let status = Command::new(ENV)
        .arg("git")
        .arg("clone")
        .arg(url)
        .arg(outdir)
        .status();

    let status = status.expect("Failed to spawn git clone");

    if !status.success() {
        println!("git clone returned nonzero status");
        return BootstrapResponse_Code::EURL;
    }

    let status = Command::new(ENV)
        .current_dir(outdir)
        .arg("git")
        .arg("checkout")
        .arg(rev)
        .status();

    let status = status.expect("Failed to spawn git checkout");

    if !status.success() {
        println!("git checkout returned nonzero status");
        return BootstrapResponse_Code::EREV;
    }

    return BootstrapResponse_Code::OK;
}

fn cmake_configure_project(project_path: &PathBuf, opt: &str) -> bool {

    let current_path = current_dir().unwrap();
    let build_path = project_path.clone().join("build");

    match create_dir_all(&build_path) {
        Err(_) => {
            println!("Failed to create directory");
            return false;
        }
        Ok(_) => ()
    }

    set_current_dir(&build_path).expect("Changing dir failed.");

    let status = Command::new(ENV)
        .arg("cmake")
        .arg("..")
        .arg(opt)
        .status();

    let status = status.expect("Failed to configure with cmake");

    if !status.success() {
        println!("Cmake project configuration failed.");
        return false;
    }

    set_current_dir(&current_path).expect("Restoring current dir failed.");

    return true;
}

fn handle_project_init(request: BootstrapRequest) -> BootstrapResponse {
    let mut response = BootstrapResponse::default();
    response.set_code(BootstrapResponse_Code::OK);

    let url = request.get_url();
    let rev = request.get_rev();

    let name_begin = url.rfind("/");

    // Cant make it work with match syntax
    if name_begin == None {
        response.set_code(BootstrapResponse_Code::EURL);
        return response;
    }

    let name_begin = name_begin.unwrap() + 1;

    let name_end = match url.rfind(".git") {
        None => url.len(),
        Some(index) => index,
    };

    let repo_name = &url[name_begin..name_end];
    println!("Got repo {}", repo_name);

    let outdir = repo_outdir(repo_name, rev);
    let outdir_str = outdir.to_str().unwrap();
    println!("Got outdir: {}", outdir_str);

    let clone_status = repo_clone(&url, outdir_str, &rev);

    if clone_status != BootstrapResponse_Code::OK {
        response.set_code(clone_status);
        return response;
    }

    if !cmake_configure_project(&outdir, "-DCMAKE_BUILD_TYPE=RELEASE") {
        response.set_code(BootstrapResponse_Code::ECFG);
        return response;
    }

    println!("{} initialized successfully with HEAD at {}", repo_name, rev);

    return response;
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

    let bootstrap_request = recv_protobuf::<BootstrapRequest>(&mut ws);
    let bootstrap_response = handle_project_init(bootstrap_request);
    let outdata = websocket::Message::binary(register_request.write_to_bytes().unwrap());
    ws.send_message(&outdata).unwrap();

}

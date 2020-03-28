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
use std::fs::File;
use std::process::Command;

use std::str::from_utf8;

use std::io::prelude::*;

use websocket::client::ClientBuilder;

type Websock = websocket::sync::Client<std::net::TcpStream>;
type BinFileData = Vec<u8>;
type BinFileError = String;
type CompileStatus = Result<BinFileData, BinFileError>;

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

    if let Err(_) = create_dir_all(&build_path) {
        println!("Failed to create directory");
        return false;
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

    //TODO(holz) Old path must be resotred in case files from another project has to be compiled.
    //set_current_dir(&current_path).expect("Restoring current dir failed.");

    return true;
}

fn handle_project_init(request: BootstrapRequest) -> BootstrapResponse {
    let mut response = BootstrapResponse::default();
    response.set_code(BootstrapResponse_Code::OK);

    let url = request.get_url();
    let rev = request.get_rev();

    let name_begin = url.rfind("/");

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

// ASSUME: output contains proper output from make VERBOSE=1. Status of make should be checked
// before call to this function.
fn get_output_path_after_compile_(output: &Vec<u8>) -> &[u8] {
    const SPACE : char = ' ';
    let mut lines = output.lines();
    let line = lines.next().unwrap().unwrap();
    let start_index = line.rfind(|c| c == SPACE).unwrap();
    let output_path = &output[start_index+1..line.len()];
    return output_path;
}

fn compile(file_name: &str) -> CompileStatus {
    let spawn_status = Command::new(ENV)
        .arg("make")
        .arg("VERBOSE=1")
        .arg(file_name)
        .output();

    if let Err(_) = spawn_status {
        return Err("Failed to start make".to_string());
    };

    let output = spawn_status.unwrap();

    if !output.status.success() {
        return Err("Failed to compile".to_string());
    }

    let output_path = get_output_path_after_compile_(&output.stdout);
    if let Ok(s) = from_utf8(output_path) {
        println!("Got file path {}", s);
    } else {
        return Err("Failed ... path".to_string());
    }

    let mut output_file = String::from(from_utf8(output_path).unwrap());
    let mut file = File::open(output_file).expect("");
    //match file {
    //    Ok(_) => { } // skip
    //    Err(_) => { return Err("Failed to open just compiled file".to_string()); }
    //}

    //let mut file = file.unwrap();
    let mut obj = Vec::new();
    if let Err(_) = file.read_to_end(&mut obj) {
        return Err("Failed to read just opened file.".to_string());
    }

    Ok(obj)
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
    // TODO(holz) obv check why this returns empty slice.
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
    let outdata = websocket::Message::binary(bootstrap_response.write_to_bytes().unwrap());
    ws.send_message(&outdata).unwrap();

    let compile_request = recv_protobuf::<CompileRequest>(&mut ws);
    let file_to_compile = compile_request.get_files();
    println!("Got {} to compile", file_to_compile);

    let mut compile_response = CompileResponse::default();
    compile_response.set_file(file_to_compile.to_string());

    match compile(file_to_compile) {
        Ok(bin_data) => {
            println!("Compiled {}", file_to_compile);
            compile_response.set_error("".to_string());
            compile_response.set_data(bin_data);
        }

        Err(error) => {
            println!("Failed to compile {}", file_to_compile);
            compile_response.set_data(Vec::<u8>::new());
            compile_response.set_error(error);
        }
    };

    let outdata = websocket::Message::binary(compile_response.write_to_bytes().unwrap());
    ws.send_message(&outdata).unwrap();
}

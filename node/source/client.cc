#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>

#include <fmt/format.h>
#include <cstdlib>
#include <string_view>

#include <sys/types.h>
#include <unistd.h>
#include <filesystem>

#include <chrono>
#include <thread>

#include <algorithm>

using namespace std::chrono_literals;

#include "delegate.pb.h"
#include "process.h"

using namespace boost;

namespace http = beast::http;
namespace websocket = beast::websocket;
using tcp = asio::ip::tcp;

namespace fs = std::filesystem;

using fmt::print;

static std::string current_commit(const char *cwd) noexcept
{
	constexpr size_t hash_size = 40;
	std::string hash;
	
	const char *argv[] = {process::env, "git", "rev-parse", "HEAD", nullptr};
	process proc(process::env, argv, cwd);

	if (proc.pid() == process::INVALID_PID)
		return hash;

	int status;
	proc.waitpid(&status);

	if (status)
		return hash;

	hash = std::string(hash_size, 0);
	status = proc.read(hash.data(), hash_size);

	fmt::print("Status: {}\n Hash: {}\n", status, hash);

	if (status != hash_size)
		hash.resize(0);

	return hash;
}

static fs::path repo_outdir(std::string_view name, std::string_view rev)
{
	// TODO Delete this slow garbage
	return fs::path(name) / fs::path(rev);
}

static bool repo_ready(const char *outdir)
{
	// TODO Make this check work better
	// Directory existance != (good clone && good checkout)
	return fs::is_directory(outdir);
}

static BootstrapResponse_Code repo_clone(const char *repo_url, const char *outdir, const char *commit = nullptr) noexcept
{
	if (repo_ready(outdir)) {
		fmt::print("{} already exists at {}. Using existing instead.\n", repo_url, outdir);
		return BootstrapResponse::OK;
	}

	const char *clone_argv[] = {process::env, "git", "clone", repo_url, outdir, nullptr};

	int status;
	process proc(process::env, clone_argv);

	if (proc.pid() == process::INVALID_PID)
		return BootstrapResponse::EURL;

	proc.waitpid(&status);

	if (status)
		return BootstrapResponse::EURL;

	if (!commit)
		return BootstrapResponse::OK;

	const char *checkout_argv[] = {process::env, "git", "checkout", commit, nullptr};

	proc = process::process_arg{process::env, checkout_argv, outdir};

	if (proc.pid() == process::INVALID_PID)
		return BootstrapResponse::EREV;

	proc.waitpid(&status);

	if (status)
		return BootstrapResponse::EREV;

	return BootstrapResponse::OK;
}

static int cmake_configure_project(const fs::path &project_path, std::string opt)  noexcept
{
	(void) opt;

	int retval = 0;

	// For now only one option is supported (low hanging fruit)
	// TODO add support for more options.
	assert(opt.find(' ') == std::string::npos);

	fs::path current_path = fs::current_path();
	fs::path build_path = fs::path(project_path) / fs::path("build");
	fs::create_directories(build_path);
	if (chdir(build_path.c_str()))
		return 1;

	const char *configure_argv[] = {process::env, "cmake", "..", opt.c_str(), nullptr};

	int status;
	process proc(process::env, configure_argv);

	if (proc.pid() == process::INVALID_PID) {
		fmt::print("Failed to spawn cmake process.\n");
		retval = 2;
		goto exit;
	}

	proc.waitpid(&status);

	if (status) {
		fmt::print("Failed to configure project with cmake.\n");
		retval = status;
		goto exit;
	}

	fmt::print("Project configured correctly.\n");

exit:
	chdir(current_path.c_str());
	return retval;
}

static BootstrapResponse handle_project_init(const BootstrapRequest &request) noexcept
{
	BootstrapResponse ret; ret.set_code(BootstrapResponse::OK);
	const auto& url = request.url();
	const auto& rev = request.rev();

	auto name_begin = url.rfind("/");

	if (name_begin == std::string::npos) {
		ret.set_code(BootstrapResponse::EURL);
		return ret;
	}

	++name_begin; // skip '/'
	auto name_end = url.find(".git", name_begin); // npos is ok

	std::string repo_name(url, name_begin, name_end);
	fs::path outdir = repo_outdir(repo_name, rev);

	BootstrapResponse_Code ret_code = repo_clone(url.c_str(), outdir.c_str(), rev.c_str());

	if (ret_code != BootstrapResponse::OK) {
		ret.set_code(ret_code);
		return ret;
	}

	if (cmake_configure_project(outdir, "-DCMAKE_BUILD_TYPE=RELEASE")) {
		ret.set_code(BootstrapResponse::ECFG);
		return ret;
	}

	fmt::print("{} initialized successfully with HEAD at: {}\n", repo_name, rev);

	return ret;
}

using websocket_t = websocket::stream<tcp::socket>;

//template <typename T>
//auto websocket_write(websocket_t &ws, T&& pb_message, std::string &serialize_buffer)
//{
//	size_t written = 0;
//	uint32_t packet_size = pb_message.ByteSizeLong();
//	written += ws.write(asio::buffer(&packet_size, sizeof(packet_size)));
//	pb_message.SerializeToString(&serialize_buffer);
//	written += ws.write(asio::buffer(serialize_buffer));
//
//	return written;
//}
//
//template <typename T>
//auto websocket_read_n(websocket_t &ws, void *outbuf_, size_t size, beast::flat_buffer &read_buffer)
//{
//	char *outbuf = (char*) outbuf_;
//	size_t bytes_read = 0;
//
//	while (bytes_read < size) {
//		ws.read(read_buffer);
//		size_t to_read = std::min(size - bytes_read, read_buffer.size());
//		std::copy_n(read_buffer.cdata().data(), to_read, outbuf);
//		bytes_read += 
//		outbuf += 
//	}
//}
//
//template <typename T>
//auto websocket_read(websocket_t &ws, T& pb_message, beast::flat_buffer &read_buffer)
//{
//	uint32_t packet_size = 0;
//	ws.read(read_buffer);
//	std::copy_n(read_buffer.cdata().data(), 4, (void*) &packet_size);
//	RegisterNodeResponse res;
//	res.ParseFromArray(read_buffer.cdata().data(), read_buffer.size());
//}

int main(int argc, char **argv)
{
	if (argc != 4)
		return 1;

	const auto host = argv[1];
	const auto port = argv[2];
	const auto resource = argv[3];

	asio::io_context ioctx;
	tcp::resolver resolver(ioctx);
	websocket::stream<tcp::socket> ws(ioctx);

	const auto resolve_res = resolver.resolve(host, port);

	asio::connect(ws.next_layer(), std::cbegin(resolve_res), std::cend(resolve_res));

	std::string message_buffer;
	beast::flat_buffer io_buffer;
	uint32_t packet_size;

	try {
		ws.handshake(host, resource);

		// Node registration
		RegisterNodeRequest register_request;
		register_request.set_version(1);
		register_request.SerializeToString(&message_buffer);
		ws.write(asio::buffer(message_buffer));


		puts("HERE1");
		// Registration response
		ws.read(io_buffer);
		RegisterNodeResponse res;
		res.ParseFromArray(io_buffer.cdata().data(), io_buffer.size());

		if (res.code() != 0)
			return 3;

		puts("HERE2");
		// Wait for BootstrapRequest and parse
		ws.read(io_buffer);
		BootstrapRequest bootstrap_request;
		bootstrap_request.ParseFromArray(io_buffer.cdata().data(), io_buffer.size());

		// Send bootstrap status
		BootstrapResponse bootstrap_response = handle_project_init(bootstrap_request);
		bootstrap_response.SerializeToString(&message_buffer);
		ws.write(asio::buffer(message_buffer));

		if (bootstrap_response.code() != BootstrapResponse::OK) {
			ws.close(websocket::close_code::normal);
			return 2;
		}

		puts("HERE3");
		// Wait for compilation request
		ws.read(io_buffer);
		CompileRequest compile_request;
		compile_request.ParseFromArray(io_buffer.cdata().data(), io_buffer.size());

		// HARD WORK, COMPILE
		std::this_thread::sleep_for(1s);

		puts("HERE4");
		// Send compilation response
		CompileResponse compile_response;
		compile_response.set_file(compile_request.files());
		compile_response.set_error("no error really");
		compile_response.set_data("\x41\x42\x43\x44");
		compile_response.SerializeToString(&message_buffer);
		ws.write(asio::buffer(message_buffer));

		puts("HERE5");

	} catch (const std::exception &e) {
		print("Exception: {}\n", e.what());
		return 2;
	}

	return 0;
}

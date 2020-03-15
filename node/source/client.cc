#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>

#include <fmt/format.h>
#include <cstdlib>
#include <string_view>

#include <sys/types.h>
#include <unistd.h>

#include "delegate.pb.h"
#include "process.h"

using namespace boost;

namespace http = beast::http;
namespace websocket = beast::websocket;
using tcp = asio::ip::tcp;

using fmt::print;

int repo_clone(const char *repo_name)
{
	const char *env = "/usr/bin/env";
	const char *argv[] = {env, "git", "clone", repo_name, nullptr};

	process proc(env, argv);

	if (proc.pid() == process::INVALID_PID)
		return -1;

	
	return 0;
}

int main(int argc, char **argv)
{
	if (argc != 4)
		return -1;

	const auto host = argv[1];
	const auto port = argv[2];
	const auto resource = argv[3];

	asio::io_context ioctx;
	tcp::resolver resolver(ioctx);
	websocket::stream<tcp::socket> ws(ioctx);

	const auto resolve_res = resolver.resolve(host, port);

	asio::connect(ws.next_layer(), std::cbegin(resolve_res), std::cend(resolve_res));

	RegisterNodeRequest req;
	req.set_version(1);

	std::string msg;

	try {
		ws.handshake(host, resource);
		req.SerializeToString(&msg);
		ws.write(asio::buffer(msg));

	} catch (const std::exception &e) {
		print("Exception: {}\n", e.what());
		return -2;
	}


	beast::flat_buffer buffer;
	ws.read(buffer);

	RegisterNodeResponse res;
	res.ParseFromArray(buffer.cdata().data(), buffer.size());
	buffer.clear();

	print("Response: {}\n", res.code());


	ws.read(buffer);

	BootstrapRequest bootstrap_request;
	bootstrap_request.ParseFromArray(buffer.cdata().data(), buffer.size());

	const auto& url = bootstrap_request.url();
	auto name_begin = url.rfind("/");
	auto name_end = url.find(".git", name_begin);

	std::string repo_name(url, name_begin, name_end);

	if (repo_clone(url.c_str()))
		return -1;

	ws.close(websocket::close_code::normal);

	return 0;
}

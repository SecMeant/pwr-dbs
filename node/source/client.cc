#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>

#include <fmt/format.h>

using namespace boost;

namespace http = beast::http;
namespace websocket = beast::websocket;
using tcp = asio::ip::tcp;

using fmt::print;

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

	std::string msg = "Hello from cpp!";

	try {
		ws.handshake(host, resource);
		ws.write(asio::buffer(msg));

	} catch (const std::exception &e) {
		print("Exception: {}\n", e.what());
		return -2;
	}

	beast::flat_buffer buffer;
	ws.read(buffer);
	print("Msg: {}\n", (char*)buffer.data().data());

	ws.close(websocket::close_code::normal);

	return 0;
}

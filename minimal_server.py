import argparse
import asyncio

HTTP_RESPONSE = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Length: 2\r\n"
    b"Connection: close\r\n"
    b"\r\nOK"
)


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Read request headers (with a short timeout), then reply and close."""
    try:
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2.0)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError):
        pass

    writer.write(HTTP_RESPONSE)

    try:
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def run_server(host: str, port: int) -> None:
    server = await asyncio.start_server(handle_connection, host, port)
    print(f"listening on http://{host}:{port}")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        asyncio.run(run_server(args.host, args.port))
    except KeyboardInterrupt:
        pass

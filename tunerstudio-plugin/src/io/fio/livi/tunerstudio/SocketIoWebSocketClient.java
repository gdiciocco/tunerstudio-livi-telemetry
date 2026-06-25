package io.fio.livi.tunerstudio;

import java.io.ByteArrayOutputStream;
import java.io.Closeable;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.Charset;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Locale;
import javax.net.ssl.SSLSocketFactory;

final class SocketIoWebSocketClient implements Closeable {
    private static final Charset UTF8 = Charset.forName("UTF-8");
    private static final SecureRandom RANDOM = new SecureRandom();

    private final String url;
    private Socket socket;
    private InputStream input;
    private OutputStream output;
    private Thread readerThread;
    private boolean connected;

    SocketIoWebSocketClient(String url) {
        this.url = normalize(url);
    }

    synchronized void connect() throws IOException {
        closeSocketOnly();
        URI uri = parseUri(url);
        String scheme = uri.getScheme() == null ? "ws" : uri.getScheme().toLowerCase(Locale.US);
        String host = uri.getHost();
        if (host == null || host.length() == 0) {
            throw new IOException("Invalid LIVI WebSocket URL: " + url);
        }
        int port = uri.getPort();
        if (port < 0) {
            port = "wss".equals(scheme) ? 443 : 80;
        }

        if ("wss".equals(scheme)) {
            socket = SSLSocketFactory.getDefault().createSocket();
            socket.connect(new InetSocketAddress(host, port), 3000);
        } else if ("ws".equals(scheme)) {
            socket = new Socket();
            socket.connect(new InetSocketAddress(host, port), 3000);
        } else {
            throw new IOException("Unsupported LIVI WebSocket scheme: " + scheme);
        }
        socket.setSoTimeout(5000);
        input = socket.getInputStream();
        output = socket.getOutputStream();

        String key = websocketKey();
        String path = socketIoPath(uri);
        StringBuilder request = new StringBuilder(320);
        request.append("GET ").append(path).append(" HTTP/1.1\r\n");
        request.append("Host: ").append(host).append(':').append(port).append("\r\n");
        request.append("Upgrade: websocket\r\n");
        request.append("Connection: Upgrade\r\n");
        request.append("Sec-WebSocket-Key: ").append(key).append("\r\n");
        request.append("Sec-WebSocket-Version: 13\r\n");
        request.append("\r\n");
        output.write(request.toString().getBytes(UTF8));
        output.flush();

        String response = readHttpHeader(input);
        if (response.indexOf(" 101 ") < 0) {
            throw new IOException("WebSocket upgrade failed: " + firstLine(response));
        }

        String handshake = readTextFrame();
        if (handshake == null || !handshake.startsWith("0")) {
            throw new IOException("Engine.IO WebSocket handshake failed");
        }
        writeTextFrame("40");
        waitForSocketIoOpen();
        socket.setSoTimeout(0);
        connected = true;
        startReaderThread();
    }

    synchronized void emit(String event, String payloadJson) throws IOException {
        if (!connected) {
            connect();
        }
        try {
            writeTextFrame("42[\"" + JsonUtil.escape(event) + "\"," + payloadJson + "]");
        } catch (IOException first) {
            connected = false;
            closeSocketOnly();
            connect();
            writeTextFrame("42[\"" + JsonUtil.escape(event) + "\"," + payloadJson + "]");
        }
    }

    public synchronized void close() {
        if (connected) {
            try {
                writeTextFrame("41");
            } catch (IOException ignored) {
            }
        }
        connected = false;
        closeSocketOnly();
    }

    private void startReaderThread() {
        readerThread = new Thread(new Runnable() {
            public void run() {
                readLoop();
            }
        }, "livi-socketio-reader");
        readerThread.setDaemon(true);
        readerThread.start();
    }

    private void waitForSocketIoOpen() throws IOException {
        while (true) {
            String message = readTextFrame();
            if (message == null) {
                throw new EOFException("Socket.IO connection closed before open");
            }
            if (message.startsWith("40")) {
                return;
            }
            if ("2".equals(message)) {
                writeTextFrame("3");
            }
        }
    }

    private void readLoop() {
        while (true) {
            String message;
            try {
                message = readTextFrame();
            } catch (IOException ex) {
                synchronized (this) {
                    connected = false;
                }
                return;
            }
            if (message == null) {
                synchronized (this) {
                    connected = false;
                }
                return;
            }
            if ("2".equals(message)) {
                try {
                    synchronized (this) {
                        if (connected) {
                            writeTextFrame("3");
                        }
                    }
                } catch (IOException ignored) {
                    synchronized (this) {
                        connected = false;
                    }
                    return;
                }
            }
        }
    }

    private String readTextFrame() throws IOException {
        Frame frame = readFrame(input);
        if (frame == null) {
            return null;
        }
        if (frame.opcode == 8) {
            connected = false;
            return null;
        }
        if (frame.opcode == 9) {
            writeFrame(10, frame.payload);
            return readTextFrame();
        }
        if (frame.opcode != 1) {
            return readTextFrame();
        }
        return new String(frame.payload, UTF8);
    }

    private synchronized void writeTextFrame(String text) throws IOException {
        writeFrame(1, text.getBytes(UTF8));
    }

    private void writeFrame(int opcode, byte[] payload) throws IOException {
        if (output == null) {
            throw new EOFException("WebSocket is not connected");
        }
        int length = payload.length;
        ByteArrayOutputStream frame = new ByteArrayOutputStream(length + 16);
        frame.write(0x80 | (opcode & 0x0f));
        byte[] mask = new byte[4];
        RANDOM.nextBytes(mask);
        if (length <= 125) {
            frame.write(0x80 | length);
        } else if (length <= 65535) {
            frame.write(0x80 | 126);
            frame.write((length >>> 8) & 0xff);
            frame.write(length & 0xff);
        } else {
            frame.write(0x80 | 127);
            long longLength = length;
            for (int i = 7; i >= 0; i--) {
                frame.write((int) ((longLength >>> (8 * i)) & 0xff));
            }
        }
        frame.write(mask, 0, mask.length);
        for (int i = 0; i < payload.length; i++) {
            frame.write(payload[i] ^ mask[i % 4]);
        }
        output.write(frame.toByteArray());
        output.flush();
    }

    private static Frame readFrame(InputStream input) throws IOException {
        int b0 = input.read();
        if (b0 < 0) {
            return null;
        }
        int b1 = readByte(input);
        int opcode = b0 & 0x0f;
        boolean masked = (b1 & 0x80) != 0;
        long length = b1 & 0x7f;
        if (length == 126) {
            length = ((long) readByte(input) << 8) | readByte(input);
        } else if (length == 127) {
            length = 0;
            for (int i = 0; i < 8; i++) {
                length = (length << 8) | readByte(input);
            }
        }
        if (length > Integer.MAX_VALUE) {
            throw new IOException("WebSocket frame too large");
        }
        byte[] mask = null;
        if (masked) {
            mask = new byte[] {
                (byte) readByte(input),
                (byte) readByte(input),
                (byte) readByte(input),
                (byte) readByte(input)
            };
        }
        byte[] payload = new byte[(int) length];
        int offset = 0;
        while (offset < payload.length) {
            int read = input.read(payload, offset, payload.length - offset);
            if (read < 0) {
                throw new EOFException("Unexpected end of WebSocket frame");
            }
            offset += read;
        }
        if (mask != null) {
            for (int i = 0; i < payload.length; i++) {
                payload[i] = (byte) (payload[i] ^ mask[i % 4]);
            }
        }
        return new Frame(opcode, payload);
    }

    private static int readByte(InputStream input) throws IOException {
        int value = input.read();
        if (value < 0) {
            throw new EOFException("Unexpected end of stream");
        }
        return value;
    }

    private static String readHttpHeader(InputStream input) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(512);
        int previous3 = -1;
        int previous2 = -1;
        int previous1 = -1;
        while (true) {
            int value = input.read();
            if (value < 0) {
                throw new EOFException("Unexpected end of HTTP response");
            }
            bytes.write(value);
            if (previous3 == '\r' && previous2 == '\n' && previous1 == '\r' && value == '\n') {
                return new String(bytes.toByteArray(), UTF8);
            }
            previous3 = previous2;
            previous2 = previous1;
            previous1 = value;
            if (bytes.size() > 16384) {
                throw new IOException("HTTP response header too large");
            }
        }
    }

    private static String socketIoPath(URI uri) {
        String path = uri.getRawPath();
        if (path == null || path.length() == 0 || "/".equals(path)) {
            path = "/socket.io/";
        }
        String query = uri.getRawQuery();
        String engineQuery = "EIO=4&transport=websocket";
        if (query == null || query.length() == 0) {
            return path + "?" + engineQuery;
        }
        if (query.indexOf("transport=") >= 0) {
            return path + "?" + query;
        }
        return path + "?" + query + "&" + engineQuery;
    }

    private static URI parseUri(String text) throws IOException {
        try {
            return new URI(text);
        } catch (URISyntaxException ex) {
            throw new IOException("Invalid LIVI WebSocket URL: " + text, ex);
        }
    }

    private static String normalize(String text) {
        String normalized = text == null || text.trim().length() == 0 ? "ws://127.0.0.1:4000" : text.trim();
        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }
        return normalized;
    }

    private static String websocketKey() {
        byte[] bytes = new byte[16];
        RANDOM.nextBytes(bytes);
        return Base64.getEncoder().encodeToString(bytes);
    }

    private static String firstLine(String text) {
        int newline = text.indexOf('\n');
        if (newline >= 0) {
            return text.substring(0, newline).trim();
        }
        return text.trim();
    }

    private void closeSocketOnly() {
        connected = false;
        if (socket != null) {
            try {
                socket.close();
            } catch (IOException ignored) {
            }
        }
        socket = null;
        input = null;
        output = null;
    }

    private static final class Frame {
        final int opcode;
        final byte[] payload;

        Frame(int opcode, byte[] payload) {
            this.opcode = opcode;
            this.payload = payload;
        }
    }
}

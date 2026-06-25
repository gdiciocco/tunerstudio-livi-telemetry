package io.fio.livi.tunerstudio;

import com.efiAnalytics.plugin.ecu.OutputChannel;
import com.efiAnalytics.plugin.ecu.OutputChannelClient;
import java.io.Closeable;
import java.io.IOException;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.nio.charset.Charset;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Timer;
import java.util.TimerTask;
import java.util.concurrent.atomic.AtomicLong;

final class TelemetryPublisher implements OutputChannelClient, Closeable {
    interface StatusSink {
        void onPublisherStatus(long sentCount, String message);
    }

    private static final Charset UTF8 = Charset.forName("UTF-8");

    private final PluginSettings settings;
    private final String ecuConfigurationName;
    private final StatusSink statusSink;
    private final AtomicLong sentCount = new AtomicLong();
    private final Map<String, String> unitsByChannel = new HashMap<String, String>();
    private final Map<String, Object> pendingPayload = new LinkedHashMap<String, Object>();
    private final Object lock = new Object();
    private final DatagramSocket udpSocket;
    private final InetAddress udpAddress;
    private final SocketIoWebSocketClient socketIoClient;
    private final LiviTelemetryMapper mapper;
    private final Timer timer;

    TelemetryPublisher(PluginSettings settings, String ecuConfigurationName, StatusSink statusSink) throws IOException {
        this.settings = settings;
        this.ecuConfigurationName = ecuConfigurationName;
        this.statusSink = statusSink;
        if (settings.directMode) {
            this.udpSocket = null;
            this.udpAddress = null;
            this.socketIoClient = new SocketIoWebSocketClient(settings.liviUrl);
            this.mapper = new LiviTelemetryMapper(settings.fieldMapFile, settings.fuelCapacityLiters);
            this.socketIoClient.connect();
            this.timer = new Timer("livi-telemetry-flush", true);
            long periodMs = Math.max(20L, Math.round(1000.0 / settings.hz));
            this.timer.scheduleAtFixedRate(new TimerTask() {
                public void run() {
                    flushDirect();
                }
            }, periodMs, periodMs);
        } else {
            this.udpSocket = new DatagramSocket();
            this.udpAddress = InetAddress.getByName(settings.udpHost);
            this.socketIoClient = null;
            this.mapper = null;
            this.timer = null;
        }
    }

    void registerChannel(OutputChannel outputChannel) {
        if (outputChannel != null && outputChannel.getName() != null) {
            unitsByChannel.put(outputChannel.getName(), outputChannel.getUnits());
        }
    }

    public void setCurrentOutputChannelValue(String outputChannelName, double rawValue) {
        if (Double.isNaN(rawValue) || Double.isInfinite(rawValue)) {
            return;
        }

        if (settings.directMode) {
            mapPending(outputChannelName, rawValue);
        } else {
            sendBridgePacket(outputChannelName, rawValue, System.currentTimeMillis());
        }
    }

    private void mapPending(String outputChannelName, double rawValue) {
        Map<String, Object> patch = mapper.map(outputChannelName, rawValue, unitsByChannel.get(outputChannelName));
        if (patch == null || patch.isEmpty()) {
            return;
        }
        synchronized (lock) {
            merge(pendingPayload, patch);
        }
    }

    private void flushDirect() {
        Map<String, Object> payload;
        synchronized (lock) {
            if (pendingPayload.isEmpty()) {
                return;
            }
            payload = new LinkedHashMap<String, Object>(pendingPayload);
            pendingPayload.clear();
        }
        payload.put("ts", Long.valueOf(System.currentTimeMillis()));
        try {
            socketIoClient.emit(settings.event, JsonUtil.object(payload));
            long count = sentCount.incrementAndGet();
            if (statusSink != null && (count == 1 || count % 100 == 0)) {
                statusSink.onPublisherStatus(count, "direct sent");
            }
        } catch (IOException ex) {
            if (statusSink != null) {
                statusSink.onPublisherStatus(sentCount.get(), ex.getMessage());
            }
        }
    }

    private void sendBridgePacket(String outputChannelName, double rawValue, long ts) {
        String json = buildBridgePacket(outputChannelName, rawValue, ts);
        byte[] bytes = json.getBytes(UTF8);
        DatagramPacket packet = new DatagramPacket(bytes, bytes.length, udpAddress, settings.udpPort);
        try {
            udpSocket.send(packet);
            long count = sentCount.incrementAndGet();
            if (statusSink != null && (count == 1 || count % 100 == 0)) {
                statusSink.onPublisherStatus(count, "bridge sent");
            }
        } catch (IOException ex) {
            if (statusSink != null) {
                statusSink.onPublisherStatus(sentCount.get(), ex.getMessage());
            }
        }
    }

    private String buildBridgePacket(String outputChannelName, double rawValue, long ts) {
        String units = unitsByChannel.get(outputChannelName);
        StringBuilder out = new StringBuilder(180);
        out.append('{');
        field(out, "source", "tunerstudio");
        out.append(',');
        field(out, "type", "outputChannel");
        out.append(',');
        field(out, "ecu", ecuConfigurationName);
        out.append(',');
        field(out, "channel", outputChannelName);
        out.append(',');
        out.append("\"value\":").append(Double.toString(rawValue));
        out.append(',');
        out.append("\"ts\":").append(Long.toString(ts));
        if (units != null && units.length() > 0) {
            out.append(',');
            field(out, "units", units);
        }
        out.append('}');
        return out.toString();
    }

    private static void field(StringBuilder out, String name, String value) {
        out.append('"').append(JsonUtil.escape(name)).append("\":");
        out.append('"').append(JsonUtil.escape(value == null ? "" : value)).append('"');
    }

    @SuppressWarnings("unchecked")
    private static void merge(Map<String, Object> target, Map<String, Object> patch) {
        for (Map.Entry<String, Object> entry : patch.entrySet()) {
            Object existing = target.get(entry.getKey());
            Object value = entry.getValue();
            if (existing instanceof Map && value instanceof Map) {
                merge((Map<String, Object>) existing, (Map<String, Object>) value);
            } else {
                target.put(entry.getKey(), value);
            }
        }
    }

    public void close() {
        if (timer != null) {
            timer.cancel();
            flushDirect();
        }
        if (socketIoClient != null) {
            socketIoClient.close();
        }
        if (udpSocket != null) {
            udpSocket.close();
        }
    }
}

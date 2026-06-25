package io.fio.livi.tunerstudio;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.net.URISyntaxException;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Properties;
import java.util.Set;

final class PluginSettings {
    private static final String PROP_CONFIG = "livi.telemetry.config";
    private static final String PROP_MODE = "livi.telemetry.mode";
    private static final String PROP_UDP_HOST = "livi.telemetry.udp.host";
    private static final String PROP_UDP_PORT = "livi.telemetry.udp.port";
    private static final String PROP_REMOTE_HOST = "livi.telemetry.remote.host";
    private static final String PROP_REMOTE_PORT = "livi.telemetry.remote.port";
    private static final String PROP_LIVI_URL = "livi.telemetry.livi.url";
    private static final String PROP_EVENT = "livi.telemetry.event";
    private static final String PROP_HZ = "livi.telemetry.hz";
    private static final String PROP_FIELD_MAP = "livi.telemetry.fieldMap";
    private static final String PROP_FUEL_CAPACITY_LITERS = "livi.telemetry.fuel.capacityLiters";
    private static final String PROP_CHANNELS = "livi.telemetry.channels";

    final String mode;
    final boolean directMode;
    final String udpHost;
    final int udpPort;
    final String liviUrl;
    final String event;
    final double hz;
    final File fieldMapFile;
    final double fuelCapacityLiters;
    final Set<String> channels;
    final boolean subscribeAll;
    final String loadedFrom;

    private PluginSettings(
        String mode,
        boolean directMode,
        String udpHost,
        int udpPort,
        String liviUrl,
        String event,
        double hz,
        File fieldMapFile,
        double fuelCapacityLiters,
        Set<String> channels,
        boolean subscribeAll,
        String loadedFrom
    ) {
        this.mode = mode;
        this.directMode = directMode;
        this.udpHost = udpHost;
        this.udpPort = udpPort;
        this.liviUrl = liviUrl;
        this.event = event;
        this.hz = hz;
        this.fieldMapFile = fieldMapFile;
        this.fuelCapacityLiters = fuelCapacityLiters;
        this.channels = channels;
        this.subscribeAll = subscribeAll;
        this.loadedFrom = loadedFrom;
    }

    static PluginSettings load() {
        Properties props = new Properties();
        String loadedFrom = "defaults";

        File config = findConfigFile();
        File configParent = null;
        if (config != null && config.isFile()) {
            FileInputStream input = null;
            try {
                input = new FileInputStream(config);
                props.load(input);
                loadedFrom = config.getAbsolutePath();
                configParent = config.getAbsoluteFile().getParentFile();
            } catch (IOException ignored) {
                loadedFrom = "defaults (failed to read " + config.getAbsolutePath() + ")";
            } finally {
                if (input != null) {
                    try {
                        input.close();
                    } catch (IOException ignored) {
                    }
                }
            }
        }

        String mode = props.getProperty(PROP_MODE, "bridge").trim().toLowerCase(Locale.US);
        boolean directMode = "direct".equals(mode) || "livi".equals(mode);
        if (!directMode && !"bridge".equals(mode)) {
            mode = "bridge";
        }

        String udpHost = props.getProperty(PROP_UDP_HOST, "127.0.0.1").trim();
        int udpPort = parsePort(props.getProperty(PROP_UDP_PORT, "8765"), 8765);
        String remoteHost = props.getProperty(PROP_REMOTE_HOST, "127.0.0.1").trim();
        int remotePort = parsePort(props.getProperty(PROP_REMOTE_PORT, "4000"), 4000);
        String liviUrl = props.getProperty(PROP_LIVI_URL, "").trim();
        if (liviUrl.length() == 0) {
            liviUrl = "ws://" + remoteHost + ":" + remotePort;
        }

        String event = props.getProperty(PROP_EVENT, "telemetry:push").trim();
        if (event.length() == 0) {
            event = "telemetry:push";
        }
        double hz = parseDouble(props.getProperty(PROP_HZ, "20"), 20.0, 0.5, 100.0);
        double fuelCapacityLiters = parseDouble(props.getProperty(PROP_FUEL_CAPACITY_LITERS, "25"), 25.0, 0.1, 10000.0);
        File fieldMapFile = resolveFile(props.getProperty(PROP_FIELD_MAP, ""), configParent);

        String channelsText = props.getProperty(PROP_CHANNELS, "*").trim();
        boolean subscribeAll = channelsText.length() == 0 || "*".equals(channelsText);
        Set<String> channels = new HashSet<String>();
        if (!subscribeAll) {
            channels.addAll(Arrays.asList(channelsText.split("\\s*,\\s*")));
        }
        return new PluginSettings(
            mode,
            directMode,
            udpHost,
            udpPort,
            liviUrl,
            event,
            hz,
            fieldMapFile,
            fuelCapacityLiters,
            channels,
            subscribeAll,
            loadedFrom
        );
    }

    boolean shouldSubscribe(String channelName) {
        return subscribeAll || channels.contains(channelName);
    }

    String targetDescription() {
        if (directMode) {
            return "direct " + liviUrl;
        }
        return "bridge UDP " + udpHost + ":" + udpPort;
    }

    private static File findConfigFile() {
        String explicit = System.getProperty(PROP_CONFIG);
        if (explicit != null && explicit.trim().length() > 0) {
            return new File(explicit.trim());
        }

        File pluginLocal = findPluginLocalConfigFile();
        if (pluginLocal != null && pluginLocal.isFile()) {
            return pluginLocal;
        }

        File local = new File("livi-telemetry.properties");
        if (local.isFile()) {
            return local;
        }

        String userHome = System.getProperty("user.home");
        if (userHome != null) {
            return new File(new File(userHome, ".livi"), "tunerstudio-livi.properties");
        }
        return null;
    }

    private static File findPluginLocalConfigFile() {
        try {
            if (PluginSettings.class.getProtectionDomain() == null
                || PluginSettings.class.getProtectionDomain().getCodeSource() == null
                || PluginSettings.class.getProtectionDomain().getCodeSource().getLocation() == null) {
                return null;
            }
            File source = new File(PluginSettings.class.getProtectionDomain().getCodeSource().getLocation().toURI());
            File directory = source.isDirectory() ? source : source.getParentFile();
            if (directory == null) {
                return null;
            }
            return new File(directory, "livi-telemetry.properties");
        } catch (SecurityException ignored) {
            return null;
        } catch (URISyntaxException ignored) {
            return null;
        } catch (IllegalArgumentException ignored) {
            return null;
        }
    }

    private static int parsePort(String text, int defaultValue) {
        try {
            int value = Integer.parseInt(text.trim());
            if (value > 0 && value <= 65535) {
                return value;
            }
        } catch (RuntimeException ignored) {
        }
        return defaultValue;
    }

    private static double parseDouble(String text, double defaultValue, double min, double max) {
        try {
            double value = Double.parseDouble(text.trim());
            if (!Double.isNaN(value) && !Double.isInfinite(value) && value >= min && value <= max) {
                return value;
            }
        } catch (RuntimeException ignored) {
        }
        return defaultValue;
    }

    private static File resolveFile(String text, File baseDir) {
        if (text == null || text.trim().length() == 0) {
            return null;
        }
        File file = new File(text.trim());
        if (file.isAbsolute() || baseDir == null) {
            return file;
        }
        return new File(baseDir, text.trim());
    }
}

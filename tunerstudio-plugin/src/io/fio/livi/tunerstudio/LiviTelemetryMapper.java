package io.fio.livi.tunerstudio;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

final class LiviTelemetryMapper {
    private final Map<String, Rule> rules = new HashMap<String, Rule>();
    private final double fuelCapacityLiters;

    LiviTelemetryMapper(File fieldMapFile, double fuelCapacityLiters) {
        this.fuelCapacityLiters = fuelCapacityLiters;
        addDefaults();
        if (fieldMapFile != null && fieldMapFile.isFile()) {
            loadTsv(fieldMapFile);
        }
    }

    Map<String, Object> map(String channel, double value, String units) {
        Rule rule = rules.get(channel);
        if (rule == null) {
            rule = rules.get(canonical(channel));
        }
        if (rule == null) {
            return null;
        }

        Object mapped = rule.apply(value, units, fuelCapacityLiters);
        Map<String, Object> patch = new LinkedHashMap<String, Object>();
        putPath(patch, rule.field, mapped);
        return patch;
    }

    private void addDefaults() {
        add("rpm", "rpm");
        add("engine", "rpm");
        add("enginespeed", "rpm");
        add("vss", "speedKph");
        add("speed", "speedKph");
        add("vehicleSpeed", "speedKph");
        add("speedmph", "speedKph", "mph_to_kph");
        add("gear", "gear", "gear");
        add("reverse", "reverse", "bool");
        add("coolant", "coolantC");
        add("clt", "coolantC");
        add("coolantc", "coolantC");
        add("coolantf", "coolantC", "f_to_c");
        add("oiltemp", "oilC");
        add("oiltempc", "oilC");
        add("oiltempf", "oilC", "f_to_c");
        add("transmissiontemp", "transmissionC");
        add("transmissiontempc", "transmissionC");
        add("iat", "iatC");
        add("mat", "iatC");
        add("airtemp", "iatC");
        add("ambient", "ambientC");
        add("ambientc", "ambientC");
        add("batteryVoltage", "batteryV");
        add("batteryv", "batteryV");
        add("batt", "batteryV");
        add("battery", "batteryV");
        add("map", "mapKpa");
        add("mapkpa", "mapKpa");
        add("mappsi", "mapKpa", "psi_to_kpa");
        add("baro", "baroKpa");
        add("barokpa", "baroKpa");
        add("boost", "boostKpa");
        add("boostkpa", "boostKpa");
        add("boostpsi", "boostKpa", "psi_to_kpa");
        add("lambda", "lambda");
        add("afr", "afr");
        add("benzina", "fuelPct");
        add("fuel", "fuelPct");
        add("fuellevel", "fuelPct");
        add("fuelpct", "fuelPct");
        add("range", "rangeKm");
        add("rangekm", "rangeKm");
        add("fuelrate", "fuelRateLph");
        add("fuelratelph", "fuelRateLph");
        add("odometer", "odometerKm");
        add("odometerkm", "odometerKm");
        add("trip", "odometerTripKm");
        add("tripkm", "odometerTripKm");
        add("ambientlux", "ambientLux");
        add("nightmode", "nightMode", "bool");
        add("gpslat", "gps.lat");
        add("latitude", "gps.lat");
        add("gpslng", "gps.lng");
        add("gpslon", "gps.lng");
        add("longitude", "gps.lng");
        add("gpsalt", "gps.alt");
        add("gpsheading", "gps.heading");
        add("gpsspeed", "gps.speedMs");
        add("gpsspeedms", "gps.speedMs");
        add("gpsspeedkph", "gps.speedMs", "kph_to_ms");
        add("gpsaccuracy", "gps.accuracyM");
        add("gpssatellites", "gps.satellites");
    }

    private void loadTsv(File file) {
        BufferedReader reader = null;
        try {
            reader = new BufferedReader(new InputStreamReader(new FileInputStream(file), "UTF-8"));
            String header = reader.readLine();
            if (header == null) {
                return;
            }
            String[] headers = header.split("\t", -1);
            int liviIndex = findColumn(headers, "livi_field");
            int tunerStudioIndex = findColumn(headers, "tunerstudio_field");
            if (liviIndex < 0 || tunerStudioIndex < 0) {
                return;
            }

            String line;
            while ((line = reader.readLine()) != null) {
                String[] parts = line.split("\t", -1);
                if (parts.length <= Math.max(liviIndex, tunerStudioIndex)) {
                    continue;
                }
                String liviField = parts[liviIndex].trim();
                String tunerStudioField = parts[tunerStudioIndex].trim();
                if (liviField.length() == 0 || tunerStudioField.length() == 0) {
                    continue;
                }
                add(tunerStudioField, liviField, defaultTransform(liviField));
            }
        } catch (IOException ignored) {
        } finally {
            if (reader != null) {
                try {
                    reader.close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private static int findColumn(String[] headers, String name) {
        for (int i = 0; i < headers.length; i++) {
            if (name.equals(headers[i].trim())) {
                return i;
            }
        }
        return -1;
    }

    private void add(String channel, String field) {
        add(channel, field, defaultTransform(field));
    }

    private void add(String channel, String field, String transform) {
        Rule rule = new Rule(field, transform);
        rules.put(channel, rule);
        rules.put(canonical(channel), rule);
    }

    private static String canonical(String name) {
        if (name == null) {
            return "";
        }
        return name.toLowerCase(Locale.US).replaceAll("[^a-z0-9]", "");
    }

    @SuppressWarnings("unchecked")
    private static void putPath(Map<String, Object> target, String path, Object value) {
        int dot = path.indexOf('.');
        if (dot < 0) {
            target.put(path, value);
            return;
        }
        String parent = path.substring(0, dot);
        String child = path.substring(dot + 1);
        Map<String, Object> nested = (Map<String, Object>) target.get(parent);
        if (nested == null) {
            nested = new LinkedHashMap<String, Object>();
            target.put(parent, nested);
        }
        nested.put(child, value);
    }

    private static String defaultTransform(String field) {
        if ("gear".equals(field)) {
            return "gear";
        }
        if ("turn".equals(field)) {
            return "turn";
        }
        if ("reverse".equals(field) || "lights".equals(field) || "highBeam".equals(field)
            || "hazards".equals(field) || "parkingBrake".equals(field) || "nightMode".equals(field)) {
            return "bool";
        }
        return "identity";
    }

    private static final class Rule {
        final String field;
        final String transform;

        Rule(String field, String transform) {
            this.field = field;
            this.transform = transform;
        }

        Object apply(double value, String units, double fuelCapacityLiters) {
            double numeric = value;
            if ("f_to_c".equals(transform)) {
                numeric = (value - 32.0) * 5.0 / 9.0;
            } else if ("mph_to_kph".equals(transform)) {
                numeric = value * 1.609344;
            } else if ("kph_to_ms".equals(transform)) {
                numeric = value / 3.6;
            } else if ("ms_to_kph".equals(transform)) {
                numeric = value * 3.6;
            } else if ("psi_to_kpa".equals(transform)) {
                numeric = value * 6.8947572932;
            } else if ("gear".equals(transform)) {
                return gear(value);
            } else if ("turn".equals(transform)) {
                return turn(value);
            } else if ("bool".equals(transform)) {
                return Boolean.valueOf(value >= 0.5);
            }

            if ("fuelPct".equals(field) && isLiterUnit(units) && fuelCapacityLiters > 0.0) {
                numeric = value * 100.0 / fuelCapacityLiters;
            }
            return Double.valueOf(numeric);
        }

        private static Object gear(double value) {
            int rounded = (int) Math.round(value);
            if (rounded == -1) {
                return "R";
            }
            if (rounded == 0) {
                return "N";
            }
            return Integer.valueOf(rounded);
        }

        private static String turn(double value) {
            int rounded = (int) Math.round(value);
            if (rounded == 1) {
                return "left";
            }
            if (rounded == 2) {
                return "right";
            }
            return "none";
        }

        private static boolean isLiterUnit(String units) {
            if (units == null) {
                return false;
            }
            String normalized = units.trim().toLowerCase(Locale.US);
            return "l".equals(normalized) || "lt".equals(normalized) || "liter".equals(normalized)
                || "liters".equals(normalized) || "litre".equals(normalized)
                || "litres".equals(normalized) || "litri".equals(normalized);
        }
    }
}

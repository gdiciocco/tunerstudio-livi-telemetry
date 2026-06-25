package io.fio.livi.tunerstudio;

import java.util.Iterator;
import java.util.Map;

final class JsonUtil {
    private JsonUtil() {
    }

    static String object(Map<String, Object> values) {
        StringBuilder out = new StringBuilder(256);
        appendObject(out, values);
        return out.toString();
    }

    @SuppressWarnings("unchecked")
    private static void appendValue(StringBuilder out, Object value) {
        if (value == null) {
            out.append("null");
        } else if (value instanceof String) {
            out.append('"').append(escape((String) value)).append('"');
        } else if (value instanceof Number || value instanceof Boolean) {
            out.append(value.toString());
        } else if (value instanceof Map) {
            appendObject(out, (Map<String, Object>) value);
        } else {
            out.append('"').append(escape(value.toString())).append('"');
        }
    }

    private static void appendObject(StringBuilder out, Map<String, Object> values) {
        out.append('{');
        Iterator<Map.Entry<String, Object>> iterator = values.entrySet().iterator();
        while (iterator.hasNext()) {
            Map.Entry<String, Object> entry = iterator.next();
            out.append('"').append(escape(entry.getKey())).append("\":");
            appendValue(out, entry.getValue());
            if (iterator.hasNext()) {
                out.append(',');
            }
        }
        out.append('}');
    }

    static String escape(String value) {
        StringBuilder out = new StringBuilder(value.length() + 8);
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"':
                    out.append("\\\"");
                    break;
                case '\\':
                    out.append("\\\\");
                    break;
                case '\b':
                    out.append("\\b");
                    break;
                case '\f':
                    out.append("\\f");
                    break;
                case '\n':
                    out.append("\\n");
                    break;
                case '\r':
                    out.append("\\r");
                    break;
                case '\t':
                    out.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        out.append(String.format("\\u%04x", Integer.valueOf(c)));
                    } else {
                        out.append(c);
                    }
            }
        }
        return out.toString();
    }
}

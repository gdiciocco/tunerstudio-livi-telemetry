package io.fio.livi.tunerstudio;

import com.efiAnalytics.plugin.ApplicationPlugin;
import com.efiAnalytics.plugin.ecu.ControllerAccess;
import com.efiAnalytics.plugin.ecu.ControllerException;
import com.efiAnalytics.plugin.ecu.OutputChannel;
import com.efiAnalytics.plugin.ecu.servers.OutputChannelServer;
import java.awt.BorderLayout;
import java.awt.GridLayout;
import java.io.IOException;
import java.util.logging.Level;
import java.util.logging.Logger;
import javax.swing.BorderFactory;
import javax.swing.JComponent;
import javax.swing.JLabel;
import javax.swing.JPanel;
import javax.swing.SwingUtilities;

public class LiviTelemetryPlugin extends JPanel implements ApplicationPlugin, TelemetryPublisher.StatusSink {
    private static final Logger LOG = Logger.getLogger(LiviTelemetryPlugin.class.getName());

    private final JLabel statusValue = new JLabel("not initialized");
    private final JLabel targetValue = new JLabel("-");
    private final JLabel configValue = new JLabel("-");
    private final JLabel subscribedValue = new JLabel("0");
    private final JLabel sentValue = new JLabel("0");

    private ControllerAccess controllerAccess;
    private OutputChannelServer outputChannelServer;
    private TelemetryPublisher publisher;
    private String ecuConfigurationName;

    public LiviTelemetryPlugin() {
        buildUi();
    }

    public String getIdName() {
        return "liviTelemetryBridge";
    }

    public int getPluginType() {
        return PERSISTENT_DIALOG_PANEL;
    }

    public String getDisplayName() {
        return "LIVI Telemetry Bridge";
    }

    public String getDescription() {
        return "Streams TunerStudio output channels to LIVI directly or through the Linux bridge.";
    }

    public void initialize(ControllerAccess controllerAccess) {
        this.controllerAccess = controllerAccess;
        closePublisher();

        PluginSettings settings = PluginSettings.load();
        targetValue.setText(settings.targetDescription());
        configValue.setText(settings.loadedFrom);

        try {
            String[] names = controllerAccess.getEcuConfigurationNames();
            if (names == null || names.length == 0) {
                setStatus("no ECU configuration");
                return;
            }

            ecuConfigurationName = names[0];
            outputChannelServer = controllerAccess.getOutputChannelServer();
            publisher = new TelemetryPublisher(settings, ecuConfigurationName, this);

            int subscribed = subscribeOutputChannels(settings);
            subscribedValue.setText(Integer.toString(subscribed));
            setStatus("streaming " + ecuConfigurationName);
        } catch (IOException ex) {
            LOG.log(Level.SEVERE, "Unable to start LIVI telemetry publisher", ex);
            setStatus("publisher error: " + ex.getMessage());
        } catch (ControllerException ex) {
            LOG.log(Level.SEVERE, "Unable to subscribe to TunerStudio output channels", ex);
            setStatus("TunerStudio error: " + ex.getMessage());
        }
    }

    public boolean displayPlugin(String controllerSignature) {
        return controllerSignature != null && controllerSignature.length() > 0;
    }

    public boolean isMenuEnabled() {
        return true;
    }

    public String getAuthor() {
        return "f-io / LIVI";
    }

    public JComponent getPluginPanel() {
        return this;
    }

    public void close() {
        closePublisher();
    }

    public String getHelpUrl() {
        return null;
    }

    public String getVersion() {
        return "0.2.0";
    }

    public double getRequiredPluginSpec() {
        return 1.0;
    }

    public void onPublisherStatus(final long sentCount, final String message) {
        SwingUtilities.invokeLater(new Runnable() {
            public void run() {
                sentValue.setText(Long.toString(sentCount));
                if (message != null && message.length() > 0) {
                    statusValue.setText(message);
                }
            }
        });
    }

    private int subscribeOutputChannels(PluginSettings settings) throws ControllerException {
        String[] channelNames = outputChannelServer.getOutputChannels(ecuConfigurationName);
        int subscribed = 0;
        for (int i = 0; i < channelNames.length; i++) {
            String channelName = channelNames[i];
            if (!settings.shouldSubscribe(channelName)) {
                continue;
            }

            OutputChannel outputChannel = outputChannelServer.getOutputChannel(ecuConfigurationName, channelName);
            publisher.registerChannel(outputChannel);
            outputChannelServer.subscribe(ecuConfigurationName, channelName, publisher);
            subscribed++;
        }
        return subscribed;
    }

    private void closePublisher() {
        if (outputChannelServer != null && publisher != null) {
            outputChannelServer.unsubscribe(publisher);
        }
        if (publisher != null) {
            publisher.close();
            publisher = null;
        }
    }

    private void setStatus(String text) {
        statusValue.setText(text == null ? "" : text);
    }

    private void buildUi() {
        setLayout(new BorderLayout(8, 8));
        setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));

        JPanel rows = new JPanel(new GridLayout(0, 2, 8, 5));
        rows.setBorder(BorderFactory.createTitledBorder("LIVI telemetry"));
        rows.add(new JLabel("Status"));
        rows.add(statusValue);
        rows.add(new JLabel("Target"));
        rows.add(targetValue);
        rows.add(new JLabel("Config"));
        rows.add(configValue);
        rows.add(new JLabel("Subscribed channels"));
        rows.add(subscribedValue);
        rows.add(new JLabel("Packets sent"));
        rows.add(sentValue);

        add(rows, BorderLayout.NORTH);
    }
}

#include "serial_protocol.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

SerialProtocol::SerialProtocol() {
}

void SerialProtocol::formatTelemetry(const DSPTelemetry& telem, char* buffer, size_t maxLen) {
    // Preserves exact contiguous "Raw:<val> Base:<val> Sig:<val> Motion:<YES/NO>"
    // pattern for 100% backward compatibility with legacy regex parsers, while
    // appending extended telemetry fields (Seq, T_us, Dt, Filt, Env, Noise, Thresh, Det).
    snprintf(buffer, maxLen,
        "Seq:%lu T_us:%lu Dt:%lu Raw:%d Base:%d Sig:%d Motion:%s Filt:%d Env:%d Noise:%d Thresh:%d Det:%u",
        (unsigned long)telem.sampleIndex,
        (unsigned long)telem.timestampUs,
        (unsigned long)telem.deltaUs,
        (int)telem.rawAdc,
        (int)telem.baselineAdc,
        (int)telem.acSignal,
        telem.selectedMotion ? "YES" : "NO",
        (int)telem.filteredSignal,
        (int)telem.envelope,
        (int)telem.noiseFloor,
        (int)telem.triggerThreshold,
        (unsigned int)telem.detectorMode
    );
}

SerialCommand SerialProtocol::parseCommandLine(const char* line) {
    SerialCommand cmd;
    cmd.type = CMD_NONE;
    cmd.intParam = 0;

    if (!line || strlen(line) == 0) {
        return cmd;
    }

    // Skip leading whitespace
    while (*line == ' ' || *line == '\t' || *line == '\r' || *line == '\n') {
        line++;
    }

    if (strncmp(line, "CMD:SET_THRESH=", 15) == 0) {
        cmd.type = CMD_SET_THRESHOLD;
        cmd.intParam = atoi(line + 15);
    } else if (strncmp(line, "SET:THRESH=", 11) == 0) {
        cmd.type = CMD_SET_THRESHOLD;
        cmd.intParam = atoi(line + 11);
    } else if (strncmp(line, "CMD:SET_DET=", 12) == 0) {
        cmd.type = CMD_SET_DETECTOR;
        cmd.intParam = atoi(line + 12);
    } else if (strncmp(line, "SET:DET=", 8) == 0) {
        cmd.type = CMD_SET_DETECTOR;
        cmd.intParam = atoi(line + 8);
    } else if (strncmp(line, "CMD:CAL", 7) == 0 || strncmp(line, "CAL", 3) == 0) {
        cmd.type = CMD_CALIBRATE;
    } else if (strncmp(line, "CMD:RESET", 9) == 0 || strncmp(line, "RST", 3) == 0) {
        cmd.type = CMD_RESET;
    } else if (strncmp(line, "CMD:GET_STATUS", 14) == 0 || strncmp(line, "STATUS", 6) == 0) {
        cmd.type = CMD_GET_STATUS;
    } else if (strncmp(line, "PING", 4) == 0) {
        cmd.type = CMD_PING;
    } else if (strncmp(line, "CMD:", 4) == 0) {
        cmd.type = CMD_UNKNOWN;
    }

    return cmd;
}

void SerialProtocol::formatStatusReport(const RadarDSP& dsp, float sampleRateHz, uint32_t timingAnomalies, char* buffer, size_t maxLen) {
    snprintf(buffer, maxLen,
        "[STATUS] Mode:%s Thresh:%d Rel:%d Noise:%d Rate:%.1fHz Events:%lu Anomalies:%lu",
        (dsp.getDetectorMode() == 1) ? "ADAPTIVE" : "LEGACY",
        (int)dsp.getTriggerThreshold(),
        (int)dsp.getReleaseThreshold(),
        (int)dsp.getEstimatedNoiseFloor(),
        sampleRateHz,
        (unsigned long)dsp.getEventCount(),
        (unsigned long)timingAnomalies
    );
}

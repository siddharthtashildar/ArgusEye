#pragma once
#include <Arduino.h>
#include "radar_dsp.h"

// ==============================================================================
// ARGUS-EYE SERIAL PROTOCOL DEFINITIONS & HANDLERS
// ==============================================================================

enum CommandType {
    CMD_NONE = 0,
    CMD_SET_THRESHOLD,
    CMD_SET_DETECTOR,
    CMD_CALIBRATE,
    CMD_RESET,
    CMD_GET_STATUS,
    CMD_PING,
    CMD_UNKNOWN
};

struct SerialCommand {
    CommandType type;
    int32_t     intParam;
};

class SerialProtocol {
public:
    SerialProtocol();

    // Serialize a DSP telemetry record to a backward-compatible, machine-parseable string
    static void formatTelemetry(const DSPTelemetry& telem, char* buffer, size_t maxLen);

    // Parse an inbound line from the PC serial interface
    static SerialCommand parseCommandLine(const char* line);

    // Format an informational/diagnostic status packet
    static void formatStatusReport(const RadarDSP& dsp, float sampleRateHz, uint32_t timingAnomalies, char* buffer, size_t maxLen);
};

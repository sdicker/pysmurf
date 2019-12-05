#ifndef _SMURF_CORE_EMULATORS_STREAMDATAEMULATOR_H_
#define _SMURF_CORE_EMULATORS_STREAMDATAEMULATOR_H_

/**
 *-----------------------------------------------------------------------------
 * Title         : SMuRF Data Emulator
 * ----------------------------------------------------------------------------
 * File          : StreamDataEmulator.h
 * Created       : 2019-10-28
 *-----------------------------------------------------------------------------
 * Description :
 *    SMuRF Data StreamDataEmulator Class
 *-----------------------------------------------------------------------------
 * This file is part of the smurf software platform. It is subject to
 * the license terms in the LICENSE.txt file found in the top-level directory
 * of this distribution and at:
    * https://confluence.slac.stanford.edu/display/ppareg/LICENSE.html.
 * No part of the smurf software platform, including this file, may be
 * copied, modified, propagated, or distributed except according to the terms
 * contained in the LICENSE.txt file.
 *-----------------------------------------------------------------------------
**/

#include <rogue/interfaces/stream/Frame.h>
#include <rogue/interfaces/stream/FrameLock.h>
#include <rogue/interfaces/stream/FrameIterator.h>
#include <rogue/interfaces/stream/FrameAccessor.h>
#include <rogue/interfaces/stream/Buffer.h>
#include <rogue/interfaces/stream/Slave.h>
#include <rogue/interfaces/stream/Master.h>
#include <rogue/GilRelease.h>
#include <rogue/Logging.h>
#include "smurf/core/common/SmurfHeader.h"
#include "smurf/core/common/Helpers.h"

namespace bp  = boost::python;
namespace ris = rogue::interfaces::stream;

namespace smurf
{
    namespace core
    {
        namespace emulators
        {
            class StreamDataEmulator;
            typedef std::shared_ptr<StreamDataEmulator> StreamDataEmulatorPtr;

            class StreamDataEmulator : public ris::Slave, public ris::Master
            {
            public:
                StreamDataEmulator();
                ~StreamDataEmulator() {};

                static StreamDataEmulatorPtr create();

                static void setup_python();

                // Accept new frames
                void acceptFrame(ris::FramePtr frame);

                // Disable the processing block. The data
                // will just pass through to the next slave
                void       setDisable(bool d);
                const bool getDisable() const;

                // Set/Get operation mode
                void      setType(int value);
                const int getType() const;

                // Set/Get signal amplitude
                void           setAmplitude(uint16_t value);
                const uint16_t getAmplitude() const;

                // Set/Get signal offset
                void          setOffset(int16_t value);
                const int16_t getOffset() const;

                // Set/Get  signal period
                void           setPeriod(uint32_t value);
                const uint32_t getPeriod() const;

            private:
                // Data types
                typedef int16_t fw_t;   // Data type from firmware

                // Types of signal
                enum class SignalType { Zeros, ChannelNumber, Random, Square, Sawtooth, Triangle, Sine, Size };

                // Signal generator methods
                void genZeroWave(ris::FrameAccessor<fw_t> &dPtr)          const;
                void genChannelNumberWave(ris::FrameAccessor<fw_t> &dPtr) const;
                void genRandomWave(ris::FrameAccessor<fw_t> &dPtr)        const;
                void genSquareWave(ris::FrameAccessor<fw_t> &dPtr)        const;
                void getSawtoothWave(ris::FrameAccessor<fw_t> &dPtr)      const;
                void genTriangleWave(ris::FrameAccessor<fw_t> &dPtr)      const;
                void genSinWave(ris::FrameAccessor<fw_t> &dPtr)           const;

                // Logger
                std::shared_ptr<rogue::Logging> eLog_;

                // Mutex
                std::mutex  mtx_;

                // Variables
                bool        disable_;   // Disable flag
                SignalType  type_;      // signal type
                uint16_t    amplitude_; // Signal amplitude
                int16_t     offset_;    // Signal offset
                uint32_t    period_;    // Signal period
            };
        }
    }
}

#endif

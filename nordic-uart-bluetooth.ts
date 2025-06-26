// nordic-uart-bluetooth.ts
const TX_CHARACTERISTIC_UUID  = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';
const RX_CHARACTERISTIC_UUID  = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
const SESAME_SERVICE_UUID     = 0xfd30;
// const SESAME_SERVICE_UUID     = '0000fd30-0000-1000-8000-00805f9b34fb;
const COMPANY_ID              = 0x065B; // Manufacturer ID to verify

export class DeviceSelectionCancelled extends Error {
}

export class IncorrectDeviceSelected extends Error {
}

export class NordicUartBle {
    private device: BluetoothDevice | null = null;
    private server: BluetoothRemoteGATTServer | null = null;
    private txChar: BluetoothRemoteGATTCharacteristic | null = null;
    private rxChar: BluetoothRemoteGATTCharacteristic | null = null;

    private static u64ToLSBUint8Array4(value: bigint): Uint8Array {
        if (value < 0n || value > 0xFFFFFFFFFFFFFFFFn) {
            throw new RangeError("Value must be an unsigned 64-bit integer");
        }

        const bytes = new Uint8Array(4);
        for (let i = 0; i < 4; i++) {
            bytes[i] = Number((value >> BigInt(i * 8)) & 0xFFn);
        }
        return bytes;
    }

    async disconnect() {
        this.server?.disconnect()
        this.server = null
    }

    /**
     * Connect to a device advertising service 0xfd30, verify manufacturer ID,
     * and get the NUS TX/RX characteristics.
     */
    async connect(lockSerial: number, disconnectCallback: () => void, listenerCallback: (event: Event) => void): Promise<void> {
        // Request device with service filter; include NUS service in optionalServices for access
        const dfuFlag = 0x08;
        const installableFlag = 0x01;
        const flagMask = dfuFlag | installableFlag;
        const options: RequestDeviceOptions = {
            filters: [{
                services: [SESAME_SERVICE_UUID], manufacturerData: [{
                    companyIdentifier: COMPANY_ID
                    , dataPrefix: new Uint8Array([0x00,0x00,0x00].concat(...NordicUartBle.u64ToLSBUint8Array4(BigInt(lockSerial))).concat([0x00,0x00,0x00,0x00,0x00]))
                    , mask: new Uint8Array([0x00,0x00,0x00,0xff,0xff,0xff,0xff,0x00,0x00,0x00,0x00,flagMask])
                }]
            }]
        };
        this.device = await navigator.bluetooth.requestDevice(options);

        if (!this.device) {
            throw new DeviceSelectionCancelled('No Bluetooth device selected');
        }

        // Verify manufacturer data via advertisement
        // await this.device.watchAdvertisements();
        // const advEvent = await new Promise<BluetoothAdvertisingEvent>((resolve, reject) => {
        //     const onAd = (event: BluetoothAdvertisingEvent) => {
        //         if (event.manufacturerData.has(COMPANY_ID)) {
        //             resolve(event);
        //         } else {
        //             reject(new Error(`Manufacturer ID 0x${COMPANY_ID.toString(16)} not found`));
        //         }
        //     };
        //     this.device!.addEventListener('advertisementreceived', onAd);
        // });

        // Connect to GATT server and get Nordic UART Service
        this.server = await this.device.gatt!.connect();

        const disconnectListener = () => {
            disconnectCallback()
            this.device.removeEventListener('gattserverdisconnected', disconnectListener)
        }
        this.device.addEventListener('gattserverdisconnected', disconnectListener);
        let service
        try {
            service = await this.server.getPrimaryService(SESAME_SERVICE_UUID);
        } catch {
            throw new IncorrectDeviceSelected()
        }

        // Get TX characteristic (central -> peripheral):contentReference[oaicite:9]{index=9}:contentReference[oaicite:10]{index=10}
        this.txChar = await service.getCharacteristic(RX_CHARACTERISTIC_UUID);

        // Get RX characteristic (peripheral -> central):contentReference[oaicite:11]{index=11}:contentReference[oaicite:12]{index=12}
        this.rxChar = await service.getCharacteristic(TX_CHARACTERISTIC_UUID);
        await this.rxChar.startNotifications();
        this.rxChar.addEventListener('characteristicvaluechanged', listenerCallback)
    }

    /**
     * Write data (ArrayBuffer) to the TX characteristic (peripheral expects this as TX).
     */
    async writeTX(data: ArrayBuffer): Promise<void> {
        if (!this.txChar) {
            throw new Error('Not connected to TX characteristic');
        }
        if (!this.device || !this.device.gatt) {
            throw new Error('Service not found or gatt property is empty');
        }
        if (!this.device.gatt.connected) {
            const server = await this.device.gatt!.connect();
            const service = await server.getPrimaryService(SESAME_SERVICE_UUID);

            // Get TX characteristic (central -> peripheral):contentReference[oaicite:9]{index=9}:contentReference[oaicite:10]{index=10}
            this.txChar = await service.getCharacteristic(RX_CHARACTERISTIC_UUID);

            // Get RX characteristic (peripheral -> central):contentReference[oaicite:11]{index=11}:contentReference[oaicite:12]{index=12}
            this.rxChar = await service.getCharacteristic(TX_CHARACTERISTIC_UUID);
        }
        console.log('txChar', this.txChar);
        console.log('rxChar', this.rxChar);
        // writeValueWithoutResponse returns a Promise and writes without requiring a response:contentReference[oaicite:13]{index=13}.
        const encoder = new TextEncoder()
        await this.txChar.writeValueWithResponse(data);
        console.log('Sent!')
    }

    /**
     * Read data from the RX characteristic. Returns a DataView of the current value.
     */
    async readRX(): Promise<DataView> {
        if (!this.rxChar) {
            throw new Error('Not connected to RX characteristic');
        }
        // readValue() returns a Promise resolving to a DataView:contentReference[oaicite:14]{index=14}.
        const value = await this.rxChar.readValue();
        return value;
    }
}

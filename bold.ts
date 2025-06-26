import {NordicUartBle, DeviceSelectionCancelled, IncorrectDeviceSelected} from "./nordic-uart-bluetooth";
import {BoldCryptor} from "./bold-cryptor";


const ble = new NordicUartBle();


function dataViewToIntArray(dataView: DataView, byteOffset = 0): number[] {
    const intArray: number[] = [];
    for (let i = byteOffset; i < dataView.byteLength; i++) {
        intArray.push(dataView.getUint8(i));
    }
    return intArray;
}

async function handleBluetoothOperation(operation: { tag: "close_bluetooth_connection" } | { data: number[]; tag: "send_bluetooth_message" } | { data: { message: number[]; serial: number }; tag: "initiate_bluetooth_connection" }) {
    switch (operation.tag) {
        case "initiate_bluetooth_connection":
            await ble.connect(operation.data.serial,
                () => {
                    // elmApp.ports.interopToElm.send({tag: "bluetooth_disconnected"})
                },
                (event: any) => {
                    console.log(`🛜 Received ${JSON.stringify(event.type)} event: 0x${BoldCryptor.arrayBufferToHex(event.target.value.buffer)}`)
                    fetch('http://localhost:8080/bluetooth_message_received', {
                        method: 'POST',
                        body: JSON.stringify({
                            tag: "bluetooth_message_received",
                            doorSerial: operation.data.serial,
                            message: (dataViewToIntArray(event.target.value))
                        })
                    }).then(response => response.json()).then((data : { tag: "send_bluetooth_message", data: number[]} | { tag: "close_bluetooth_connection" }) => {
                        handleBluetoothOperation(data)
                    })

            })
            // elmApp.ports.interopToElm.send({tag: "bluetooth_connected"})
            console.log(`🛜 Sending 0x${BoldCryptor.arrayBufferToHex(new Uint8Array(operation.data.message))}`)
            await ble.writeTX(new Uint8Array(operation.data.message))
            break;
        case "send_bluetooth_message":
            console.log(`🛜 Sending 0x${BoldCryptor.arrayBufferToHex(new Uint8Array(operation.data))}`)
            await ble.writeTX(new Uint8Array(operation.data));
            break;
        case "close_bluetooth_connection":
            await ble.disconnect();
            break;
    }
}



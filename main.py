import json
import logging
import signal
import sys

from pyhap.accessory_driver import AccessoryDriver

from accessory import Lock
from repository import Repository
from api_repository import APIRepository
from service import Service
from util.bfclf import BroadcastFrameContactlessFrontend

# By default, this file is located in the same folder as the project
CONFIGURATION_FILE_PATH = "configuration.json"


def load_configuration(path=CONFIGURATION_FILE_PATH) -> dict:
    return json.load(open(path, "r+"))


def configure_logging(config: dict):
    log = logging.getLogger()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)8s] %(module)-18s:%(lineno)-4d %(message)s"
    )
    hdlr = logging.StreamHandler(sys.stdout)
    log.setLevel(config.get("level", logging.INFO))
    hdlr.setFormatter(formatter)
    log.addHandler(hdlr)
    return log


def configure_hap_accessory(config: dict, homekey_service=None):
    driver = AccessoryDriver(port=config["port"], persist_file=config["persist"])
    accessory = Lock(
        driver,
        "NFC Lock",
        service=homekey_service,
        lock_state_at_startup=int(config.get("default") != "unlocked")
    )
    driver.add_accessory(accessory=accessory)
    return driver, accessory


def configure_nfc_device(config: dict):
    clf = BroadcastFrameContactlessFrontend(
        path=config.get("path", None) or f"tty:{config.get('port')}:{config.get('driver')}",
        broadcast_enabled=config.get("broadcast", True),
    )
    return clf


def configure_homekey_service(config: dict, nfc_device, repository=None):
    # Choose repository type based on configuration
    if repository is None:
        if config.get("use_api_repository", False):
            repository = APIRepository(
                config.get("api_base_url", "http://localhost:8080"),
                config.get("api_secret")
            )
        else:
            repository = Repository(config["persist"])
    
    service = Service(
        nfc_device,
        repository=repository,
        express=config.get("express", True),
        finish=config.get("finish", "default"),
        flow=config.get("flow", "default"),
        # Poll no more than ~6 times a second by default
        throttle_polling=float(config.get("throttle_polling") or 0.15),
        api_base_url=config.get("api_base_url", "http://localhost:8080"),
        default_lock_serial=config.get("default_lock_serial", 0),
    )
    return service


def main():
    config = load_configuration()
    log = configure_logging(config["logging"])

    nfc_device = configure_nfc_device(config["nfc"])
    homekey_service = configure_homekey_service(config["homekey"], nfc_device)
    hap_driver, _ = configure_hap_accessory(config["hap"], homekey_service)

    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(
            s,
            lambda *_: (
                log.info(f"SIGNAL {s}"),
                homekey_service.stop(),
                hap_driver.stop(),
            ),
        )

    homekey_service.start()
    hap_driver.start()


if __name__ == "__main__":
    main()

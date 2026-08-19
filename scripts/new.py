import time
import random
from datetime import datetime
import oci

config = oci.config.from_file("~/.oci/config", "DEFAULT")
compute_client = oci.core.ComputeClient(config)
virtual_network_client = oci.core.VirtualNetworkClient(config)

COMPARTMENT_ID = "ocid1.tenancy.oc1..aaaaaaaa5vzw3kjsuxib7biqaorm332dljs63d2lu4yppkvzimlwmjgcvhkq"
AVAILABILITY_DOMAINS = [
    "HXRC:EU-FRANKFURT-1-AD-1",
    "HXRC:EU-FRANKFURT-1-AD-2",
    "HXRC:EU-FRANKFURT-1-AD-3",
]
IMAGE_ID = "ocid1.image.oc1.eu-frankfurt-1.aaaaaaaafmmsrqjzb6dql6i6by4ddi4ughbvir5gbrhbkfsdpdmie5i27tka"

SSH_PUBLIC_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC/BP8Qxtb3eqHtvO89ubkryn1/CWy4dq5NBKhBVh3zvED8psmCwTFIEM0JlTBcN2NQrsdFYW+Pd0i9MC7mb6a+qkEKD5T7zRIyDa/TzYrn+mMCytfLlc4R4O4yC13ck/KtNmKqN50YlkOUuS7qHxxnGtpBPFFfy0FmORu1gWFwBl/TlV20Dtx8ZTSna/eaF9u04Ve32PuFtmRYJDWzEG4ITtjmtrfIQZbR4HZ9UZTBFvYJ2we/NxCF7Efz+O7DuEEeATmwVwpqLOEiCwFFgriAOv6VAHEymx79YMVUIVnq9avt0CyKyN6Mfk/4NZBQiXDJp56pG/aM+/ujP5IsIYuz ssh-key-2026-08-18"

subnet_id = None


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def get_or_create_network():
    global subnet_id
    if subnet_id:
        return subnet_id

    log("Создаем VCN и подсеть...")
    vcn = virtual_network_client.create_vcn(
        oci.core.models.CreateVcnDetails(
            compartment_id=COMPARTMENT_ID,
            cidr_block="10.0.0.0/16",
            display_name="auto-vcn",
        )
    ).data

    ig = virtual_network_client.create_internet_gateway(
        oci.core.models.CreateInternetGatewayDetails(
            compartment_id=COMPARTMENT_ID,
            vcn_id=vcn.id,
            is_enabled=True,
            display_name="auto-ig",
        )
    ).data

    rt = virtual_network_client.create_route_table(
        oci.core.models.CreateRouteTableDetails(
            compartment_id=COMPARTMENT_ID,
            vcn_id=vcn.id,
            route_rules=[
                oci.core.models.RouteRule(
                    network_entity_id=ig.id, destination="0.0.0.0/0"
                )
            ],
        )
    ).data

    subnet = virtual_network_client.create_subnet(
        oci.core.models.CreateSubnetDetails(
            compartment_id=COMPARTMENT_ID,
            vcn_id=vcn.id,
            cidr_block="10.0.1.0/24",
            display_name="auto-subnet",
            route_table_id=rt.id,
        )
    ).data

    subnet_id = subnet.id
    log("Сеть готова!")
    return subnet_id


round_num = 0
while True:
    round_num += 1
    log(f"Раунд #{round_num} — проверяем все 3 AD...")
    current_subnet_id = get_or_create_network()
    success = False

    for ad in AVAILABILITY_DOMAINS:
        try:
            log(f"  [{ad}] — пробуем...")
            launch_details = oci.core.models.LaunchInstanceDetails(
                compartment_id=COMPARTMENT_ID,
                availability_domain=ad,
                display_name="free-arm-server",
                shape="VM.Standard.A1.Flex",
                shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                    ocpus=1, memory_in_gbs=20
                ),
                source_details=oci.core.models.InstanceSourceViaImageDetails(
                    image_id=IMAGE_ID
                ),
                create_vnic_details=oci.core.models.CreateVnicDetails(
                    subnet_id=current_subnet_id,
                    assign_public_ip=True,
                ),
                metadata={"ssh_authorized_keys": SSH_PUBLIC_KEY},
            )
            response = compute_client.launch_instance(launch_details)
            log(f"УСПЕХ! Сервер создан в {ad}: {response.data.id}")
            success = True
            break

        except oci.exceptions.ServiceError as e:
            if "Out of host capacity" in str(e):
                log(f"  [{ad}] — нет мест.")
            else:
                log(f"  [{ad}] — ошибка сервиса: {e.status} {e.code}")
        except Exception as e:
            log(f"  [{ad}] — ошибка: {e}")

    if success:
        break

    delay = random.randint(30, 60)
    log(f"Все AD заняты. Следующий раунд через {delay} сек...")
    time.sleep(delay)

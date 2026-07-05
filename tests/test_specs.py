from ntt_pricing.extraction.specs import parse_specification
from ntt_pricing.models import DeviceType


def test_parse_mccb():
    s = parse_specification("Compact NSX250F MCCB 3P 250A 36kA TMD")
    assert s.device_type == DeviceType.MCCB
    assert s.poles == 3
    assert s.rating_amps == 250
    assert s.breaking_capacity_ka == 36


def test_parse_mcb_curve():
    s = parse_specification("Acti9 iC60N MCB 1P 16A C curve 6kA")
    assert s.device_type == DeviceType.MCB
    assert s.poles == 1
    assert s.rating_amps == 16
    assert s.breaking_capacity_ka == 6
    assert s.curve == "C"


def test_ka_not_read_as_amps():
    s = parse_specification("3P 100A 36kA MCCB")
    assert s.rating_amps == 100
    assert s.breaking_capacity_ka == 36


def test_contactor():
    s = parse_specification("TeSys D contactor 3P 80A 37kW 220V coil")
    assert s.device_type == DeviceType.CONTACTOR
    assert s.rating_amps == 80


def test_frame_trip_notation():
    s = parse_specification("MCCB 250AF 200AT 3P")
    assert s.rating_amps == 200  # trip setting wins over frame

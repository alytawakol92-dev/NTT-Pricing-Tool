"""Company profile, panel defaults and offer terms for the NTT offer format.

These capture the fixed house content of an Al-Tawakol / NTT offer — the
letterhead, the standard panel construction parameters, the standard
indication set fitted to every panel, and the commercial terms & conditions.
All of it is overridable via the pricing config so the same engine can serve
a different panel builder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class CompanyProfile:
    name: str = "Al-Tawakol For Electrical Industries - NTT"
    arabic_name: str = "التوكل للصناعات الكهربائية"
    partner_line: str = "Schneider Electric Egypt (Prisma Partner) & Panel Builder"
    address_office: str = "Head Office & Show Room: 15 Emad El Dine St., P.O.BOX 582/11511 Cairo"
    address_factory: str = "Factory: El Obour Industrial Zone (A)"
    tel: str = "(202) 25911800 - 25911102"
    fax: str = "(202) 25927843"
    website: str = "www.ntt-altawakol.com"
    intro: str = ("Al-Tawakol For Electrical Industries - NTT specializes in offering a "
                  "complete solution for you, from MV & LV Panels to Wiring Devices.")


@dataclass
class PanelDefaults:
    """Standard NTT panel construction parameters (shown on every spec sheet)."""

    voltage_system: str = "400/230 VAC"
    mounting: str = "Wall Mounted"
    control_voltage: str = "220 VAC"
    enclosure_type: str = "NTT Panel"
    ip_rating: str = "IP54"
    enclosure_material: str = "Galvanized Sheet Steel 2 mm"
    cu_insulation: str = "Tin Plated"
    temperature: str = "Temp = 40°C"
    main_bb_sizing: str = ""            # filled from incomer rating
    neutral_bb: str = "Half Size Of Main B.B"
    color_ral: str = "RAL 7035"
    earth_bb: str = "Half Size Of N.B.B"
    form: str = "Form 1"
    control_wire_size: str = "1.5 mm² (Voltage) - 2.5 mm² (Current)"
    incoming_position: str = "Bottom"
    outgoing_position: str = "Bottom"


@dataclass
class StandardAccessory:
    """A standard fitting added to the INDICATION & INSTRUMENTS group of every panel."""

    qty: int
    ref: str
    brand: str
    description: str
    unit_price: float = 0.0
    group: str = "INDICATION & INSTRUMENTS"


# The standard indication set NTT fits to every panel (red/yellow/blue lamps + fuse).
DEFAULT_ACCESSORIES: List[StandardAccessory] = [
    StandardAccessory(1, "XA2EVM4LC", "Schneider", "Indication Lamp Red", 6.5),
    StandardAccessory(1, "XA2EVM5LC", "Schneider", "Indication Lamp Yellow", 6.5),
    StandardAccessory(1, "XA2EVM6LC", "Schneider", "Indication Lamp Blue", 6.5),
    StandardAccessory(3, "Reputed", "Reputed", "Fuse + Fuse Holder", 2.5),
]


@dataclass
class OfferTerms:
    """Commercial terms & conditions (bilingual) shown on the commercial offer."""

    tax_note_en: str = "Prices are exclusive of VAT; 14% is added."
    tax_note_ar: str = "الأسعار غير شامله ضريبه القيمه المضافه وتضاف بنسبه 14%"
    validity_en: str = "Offer validity: one week from the offer date."
    validity_ar: str = "صلاحيه العرض: اسبوع من تاريخ عرض السعر"
    payment_en: str = ("Payment: 50% on contract (cash/cheque), balance on inspection "
                       "and delivery.")
    payment_ar: str = ("طريقه الدفع: 50% عند التعاقد (نقداً أو بشيك) والباقي عند الفحص "
                       "والاستلام (نقداً أو بشيك مصرفي أو ايداع بنكي في حساب شركتنا)")
    delivery_place_en: str = "Delivery location: our factories in Obour City."
    delivery_place_ar: str = "مكان الاستلام: مصانعنا بمدينه العبور"
    delivery_period_en: str = ("Delivery period: 2:4 months from the supply order date, "
                               "the advance payment and shop-drawing approval, whichever "
                               "is later; supply in batches.")
    delivery_period_ar: str = ("مده التوريد: من 2:4 شهر من تاريخ امر التوريد والدفعه المقدمه "
                               "واعتماد الرسومات التنفيذيه ايهما الحق على أن يكون التوريد على دفعات")
    storage_en: str = ("Storage fees: 2% of project value, starting two weeks after "
                       "notification of readiness, applied every two weeks.")
    storage_ar: str = ("رسوم التخزين: 2% من قيمة المشروع تبدأ بعد أسبوعين من تاريخ الاخطار "
                       "بجاهزيه استلام اللوحات يتم تطبيقه مع بدايه كل أسبوعين")
    currency_note_en: str = ("Prices are in EUR; each instalment is converted to EGP at the "
                             "Central Bank daily rate at the time of payment.")
    currency_note_ar: str = ("السعر عاليه باليورو ويتم تحويل كل دفعه بالجنيه المصري في حينه "
                             "طبقاً للسعر اليومي للبنك المركزي")


@dataclass
class Signatory:
    title: str
    name: str


DEFAULT_SIGNATORIES: List[Signatory] = [
    Signatory("Sales Engineer", "Eng. / Samer"),
    Signatory("Sales Manager", "Eng. / Ahmed Emam"),
    Signatory("Technical Office Manager", "Eng. / Mohamed Adel"),
]

DEFAULT_CONTACTS: List[str] = ["Ms. Fatma: 01094779989", "Eng. Hend: 01030051953"]

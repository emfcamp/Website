from typing import Any

shift_list: dict[str, dict[str, dict[str, Any]]] = {}

from .shifts.arcade import arcade_shifts
from .shifts.bands import bands_shifts
from .shifts.bar import bar_shifts
from .shifts.info_volunteer import info_vol_shifts
from .shifts.talks import talks_shifts
from .shifts.kitchen import kitchen_shifts
from .shifts.shop import shop_shifts
from .shifts.logistics import logistics_shifts

shift_list.update(arcade_shifts)
shift_list.update(bar_shifts)
shift_list.update(bands_shifts)
shift_list.update(info_vol_shifts)
shift_list.update(talks_shifts)
shift_list.update(kitchen_shifts)
shift_list.update(shop_shifts)
shift_list.update(logistics_shifts)

if __name__=="__main__":
    import pprint
    pprint.pp(shift_list)


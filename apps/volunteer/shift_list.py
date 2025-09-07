def get_shift_list():
    # This is a bit gross but: all the shift definitions use `edt()` which requires the
    # global app context to be up, so can't happen at import time. In addition, we only
    # ever need to load them when someone hits the init_shifts endpoint. So...
    from .shifts.arcade import arcade_shifts
    from .shifts.badge import badge_shifts
    from .shifts.bands import bands_shifts
    from .shifts.bar import bar_shifts
    from .shifts.entrance import entrance_shifts
    from .shifts.info_volunteer import info_vol_shifts
    from .shifts.kitchen import kitchen_shifts
    from .shifts.logistics import logistics_shifts
    from .shifts.nullsector import nullsector_shifts
    from .shifts.parking import parking_shifts
    from .shifts.phone import phone_shifts
    from .shifts.shop import shop_shifts
    from .shifts.talks import talks_shifts
    from .shifts.youth_workshops import youth_workshop_shifts

    shift_list = arcade_shifts
    shift_list.update(badge_shifts)
    shift_list.update(bands_shifts)
    shift_list.update(bar_shifts)
    shift_list.update(entrance_shifts)
    shift_list.update(info_vol_shifts)
    shift_list.update(kitchen_shifts)
    shift_list.update(logistics_shifts)
    shift_list.update(nullsector_shifts)
    shift_list.update(parking_shifts)
    shift_list.update(phone_shifts)
    shift_list.update(shop_shifts)
    shift_list.update(talks_shifts)
    shift_list.update(youth_workshop_shifts)

    return shift_list

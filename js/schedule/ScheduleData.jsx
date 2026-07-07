import { DateTime } from "luxon";

class ScheduleData {
  constructor(rawSchedule, options) {
    this.rawSchedule = rawSchedule;
    this.options = options;
    this.hoursWithContent = [];
    this.scheduleByHour = {};

    this.venues = [];
    this.venuesSeen = new Set();

    this.eventTypes = [];
    this.eventTypesSeen = new Set();

    this.ageRanges = [];
    this.ageRangesSeen = new Set();

    this.allFinished = true;

    let count = 0;
    this.rawSchedule.forEach((row) => {
      let sid = this.parseScheduleItem(row);

      this.addEventType(sid.type, sid.humanReadableType);
      this.addAgeRange(sid.age_range);

      for (const od of sid.occurrences) {
        // Apply filtering

        if (od.endTime >= options.currentTime) {
          this.allFinished = false;
        } else if (!options.includeFinished) {
          continue;
        }

        this.addVenue(od.venue, sid.officialEvent);

        if (
          options.selectedVenues &&
          options.selectedVenues.indexOf(od.venue) === -1
        ) {
          continue;
        }

        if (options.onlyLottery && !od.uses_lottery) {
          continue;
        }

        if (
          options.selectedEventTypes &&
          options.selectedEventTypes.indexOf(sid.type) === -1
        ) {
          continue;
        }
        if (
          options.selectedAgeRanges &&
          options.selectedAgeRanges.indexOf(sid.age_range) === -1
        ) {
          continue;
        }
        if (options.onlyFavourites && !sid.is_fave) {
          continue;
        }
        if (options.onlyFamilyFriendly && !sid.is_family_friendly) {
          continue;
        }
        if (options.onlyNoRecording && !od.noRecording) {
          continue;
        }

        // We can now add this occurrence to our schedule

        let startHour = od.startTime.startOf("hour");
        if (od.startTime <= options.currentTime && !options.includeFinished) {
          /* Put ongoing events under the current time slot to avoid
           * having to make one up or include multiple earlier ones */
          startHour = options.currentTime.startOf("hour");
        }
        let isoHour = startHour.toISO();

        if (this.scheduleByHour[isoHour] === undefined) {
          this.hoursWithContent.push(startHour);
          this.scheduleByHour[isoHour] = [];
        }
        this.scheduleByHour[isoHour].push(od);
      }
    });

    this.venuePriority = (venue) => {
      if (venue.name.startsWith("Stage")) {
        return 999;
      }
      if (venue.name.startsWith("Workshop")) {
        return 900;
      }
      return 1;
    };

    this.venues = this.venues.sort((a, b) => {
      if (a.official && !b.official) {
        return -1;
      }
      if (!a.official && b.official) {
        return 1;
      }

      // Horrible code, used for prioritising stages and workshops.
      let priority_a = this.venuePriority(a);
      let priority_b = this.venuePriority(b);
      if (priority_a > priority_b) {
        return -1;
      }
      if (priority_b > priority_a) {
        return 1;
      }

      return a.name.localeCompare(b.name);
    });

    this.ageRanges = this.ageRanges
      .map((i) => {
        return [i, parseInt(i.replace(/[^\d]+/, ""))];
      })
      .sort((a, b) => {
        // Sort things that aren't ages at the end of the list
        if (isNaN(a[1]) && !isNaN(b[1])) {
          return 1;
        }
        if (isNaN(b[1]) && !isNaN(a[1])) {
          return -1;
        }

        if (a[1] < b[1]) {
          return -1;
        }
        if (a[1] > b[1]) {
          return 1;
        }

        return 0;
      })
      .map((i) => i[0]);

    this.eventTypes = this.eventTypes.sort((a, b) =>
      a.name.localeCompare(b.name),
    );

    Object.keys(this.scheduleByHour).forEach((hour) => {
      this.scheduleByHour[hour] = this.scheduleByHour[hour].sort((a, b) => {
        let date_sort = a.start_date.localeCompare(b.start_date);
        if (date_sort !== 0) {
          return date_sort;
        }

        return a.venue.localeCompare(b.venue);
      });
    });

    this.hoursWithContent = this.hoursWithContent.sort();
  }

  addVenue(name, official) {
    if (this.venuesSeen.has(name)) {
      // FIXME: we can now use Venue.official_venue
      // More nasty hacks to handle venues with mixed content not being marked
      // as one of our's if the first event in that venue is attendee content.
      if (official) {
        this.venues.find((v) => v["name"] == name)["official"] = official;
      }
      return null;
    }

    this.venuesSeen.add(name);
    this.venues.push({ name: name, official: official });
  }

  addEventType(type, name) {
    if (this.eventTypesSeen.has(type)) {
      return null;
    }

    this.eventTypesSeen.add(type);
    this.eventTypes.push({ id: type, name });
  }

  addAgeRange(value) {
    if (this.ageRangesSeen.has(value)) {
      return null;
    }

    this.ageRangesSeen.add(value);
    this.ageRanges.push(value);
  }

  contentForHour(hour) {
    let events = this.scheduleByHour[hour.toISO()];

    return events;
  }

  parseScheduleItem(schedule_item) {
    // FIXME we shouldn't need to do this much parsing
    let sid = structuredClone(schedule_item);

    sid.officialEvent = sid.official_content;

    for (const od of sid.occurrences) {
      od.startTime = DateTime.fromSQL(od.start_date, { locale: "en-GB" });
      od.endTime = DateTime.fromSQL(od.end_date, { locale: "en-GB" });
      od.key = `${sid.id}-${od.occurrence_num}`;
      od.noRecording =
        od.video_privacy === "none" &&
        sid.officialEvent &&
        (sid.type === "talk" || sid.type === "performance");

      // Let's hope this doesn't come back to leak on us
      od.schedule_item = sid;
    }

    if (sid.type === "familyworkshop") {
      sid.humanReadableType = "Family Workshop";
    } else if (sid.type === "djset") {
      sid.humanReadableType = "DJ";
    } else {
      sid.humanReadableType =
        sid.type.charAt(0).toUpperCase() + sid.type.slice(1);
    }

    if (sid.age_range === undefined || sid.age_range == "") {
      sid.age_range = "Unspecified";
    }

    return sid;
  }
}

export default ScheduleData;

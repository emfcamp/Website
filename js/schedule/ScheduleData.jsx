import { DateTime } from 'luxon';

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

    this.rawSchedule.forEach(row => {
      let e = this.parseEvent(row);

      if (e.age_range === undefined || e.age_range == "") { e.age_range = "Unspecified" }

      this.addVenue(e.venue, e.officialEvent);
      this.addEventType(e.type, e.humanReadableType);
      this.addAgeRange(e.age_range);

      if (e.endTime >= options.currentTime) {
          this.allFinished = false;
      } else if (!options.includeFinished) {
          return null;
      }

      if (options.selectedVenues && options.selectedVenues.indexOf(e.venue) === -1) { return null; }
      if (options.selectedEventTypes && options.selectedEventTypes.indexOf(e.type) === -1) { return null; }
      if (options.selectedAgeRanges && options.selectedAgeRanges.indexOf(e.age_range) === -1) { return null; }
      if (options.onlyFavourites && !e.is_fave) { return null; }
      if (options.onlyFamilyFriendly && !e.is_family_friendly) { return null; }

      let startHour = e.startTime.startOf('hour');
      if (e.startTime <= options.currentTime && !options.includeFinished) {
        /* Put ongoing events under the current time slot to avoid
         * having to make one up or include multiple earlier ones */
        startHour = options.currentTime.startOf('hour');
      }
      let isoHour = startHour.toISO();

      if (this.scheduleByHour[isoHour] === undefined) {
        this.hoursWithContent.push(startHour);
        this.scheduleByHour[isoHour] = [];
      }
      this.scheduleByHour[isoHour].push(e);
    });

    this.venuePriority = (venue) => {
      if (venue.name.startsWith("Stage")) { return 999 }
      if (venue.name.startsWith("Workshop")) { return 900 }
      return 1;
    };

    this.venues = this.venues.sort((a,b) => {
      if (a.official && !b.official) { return -1; }
      if (!a.official && b.official) { return 1; }

      // Horrible code, used for prioritising stages and workshops.
      let priority_a = this.venuePriority(a);
      let priority_b = this.venuePriority(b);
      if (priority_a > priority_b) { return -1; }
      if (priority_b > priority_a) { return 1; }

      return a.name.localeCompare(b.name);
    });

    this.ageRanges = this.ageRanges.map(i => {
      return [i, parseInt(i.replace(/[^\d]+/, ""))]
    }).sort((a,b) => {
      // Sort things that aren't ages at the end of the list
      if (isNaN(a[1]) && !isNaN(b[1])) { return 1 }
      if (isNaN(b[1]) && !isNaN(a[1])) { return -1 }

      if (a[1] < b[1]) { return -1 }
      if (a[1] > b[1]) { return 1 }

      return 0
    }).map(i => i[0]);

    this.eventTypes = this.eventTypes.sort((a,b) => a.name.localeCompare(b.name));

    Object.keys(this.scheduleByHour).forEach(hour => {
      this.scheduleByHour[hour] = this.scheduleByHour[hour].sort((a,b) => {
        let date_sort = a.start_date.localeCompare(b.start_date);
        if (date_sort !== 0) { return date_sort; }

        return a.venue.localeCompare(b.venue);
      });
    });

    this.hoursWithContent = this.hoursWithContent.sort();
  }

  addVenue(name, official) {
    if (this.venuesSeen.has(name)) {
      // More nasty hacks to handle venues with mixed content not being marked
      // as one of our's if the first event in that venue is attendee content.
      if (official) {
        this.venues.find(v => v["name"] == name)["official"] = official;
      }
    }

    this.venuesSeen.add(name);
    this.venues.push({ name: name, official: official });
  }

  addEventType(type, name) {
    if (this.eventTypesSeen.has(type)) { return null; }

    this.eventTypesSeen.add(type);
    this.eventTypes.push({ id: type, name });
  }

  addAgeRange(value) {
    if (this.ageRangesSeen.has(value)) { return null; }

    this.ageRangesSeen.add(value);
    this.ageRanges.push(value);
  }

  contentForHour(hour) {
    let events = this.scheduleByHour[hour.toISO()];

    return events;
  }

  parseEvent(event) {
    let e = structuredClone(event);

    e.startTime = DateTime.fromSQL(e.start_date, { locale: 'en-GB' });
    e.endTime = DateTime.fromSQL(e.end_date, { locale: 'en-GB' });
    e.officialEvent = e.is_from_cfp;

    e.noRecording = !e.may_record && e.officialEvent && e.type === 'talk';

    if (e.type === 'youthworkshop') {
      e.humanReadableType = 'Youth Workshop'
    } else {
      e.humanReadableType = e.type.charAt(0).toUpperCase() + e.type.slice(1);
    };

    return e;
  }
}

export default ScheduleData;

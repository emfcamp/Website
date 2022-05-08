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

    this.rawSchedule.forEach(row => {
      let e = this.parseEvent(row);

      if (e.endTime <= options.currentTime) { return null; }
      if (e.age_range === undefined || e.age_range == "") { e.age_range = "Unspecified" }

      this.addVenue(e.venue, e.officialEvent);
      this.addEventType(e.type, e.humanReadableType);
      this.addAgeRange(e.age_range);

      if (options.selectedVenues && options.selectedVenues.indexOf(e.venue) === -1) { return null; }
      if (options.selectedEventTypes && options.selectedEventTypes.indexOf(e.type) === -1) { return null; }
      if (options.selectedAgeRanges && options.selectedAgeRanges.indexOf(e.age_range) === -1) { return null; }
      if (options.onlyFavourites && !e.is_fave) { return null; }

      let startHour = e.startTime.startOf('hour');
      if (e.startTime <= options.currentTime) {
        startHour = options.currentTime.startOf('hour');
      }
      let isoHour = startHour.toISO();

      if (this.scheduleByHour[isoHour] === undefined) {
        this.hoursWithContent.push(startHour);
        this.scheduleByHour[isoHour] = [];
      }
      this.scheduleByHour[isoHour].push(e);
    });

    this.venues = this.venues.sort((a,b) => {
      if (a.official && !b.official) { return -1; }
      if (!a.official && b.official) { return 1; }

      return a.name.localeCompare(b.name);
    });

    this.eventTypes = this.eventTypes.sort((a,b) => a.name.localeCompare(b.name));

    Object.keys(this.scheduleByHour).forEach(hour => {
      this.scheduleByHour[hour] = this.scheduleByHour[hour].sort((a,b) => a.start_date.localeCompare(b.start_date));
    });

    this.hoursWithContent = this.hoursWithContent.sort();
  }

  addVenue(name, official) {
    if (this.venuesSeen.has(name)) { return null; }

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
    // Ugh. Why do Javascript objects not just have a clone method?
    let e = JSON.parse(JSON.stringify(event));

    e.startTime = DateTime.fromSQL(e.start_date, { locale: 'en-GB' });
    e.endTime = DateTime.fromSQL(e.end_date, { locale: 'en-GB' });
    e.officialEvent = e.source === 'database';

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

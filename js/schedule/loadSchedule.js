function Schedule(rawSchedule) {
  let scheduleByHour = {};
  let options = {
    officialOnly: false,
    currentTime: new Date(),
  };
  this.options = options;

  function setOption(key, value) {
    if (key === 'currentTime' && typeof(value) === 'string') {
      value = new Date(Date.parse(value));
    }

    options[key] = value;
  }
  this.setOption = setOption;

  function setOptions(newOptions) {
    Object.keys(newOptions).forEach(key => {
      let value = newOptions[key];
      setOption(key, value);
    });
  }
  this.setOptions = setOptions;

  function contentForHour(hour) {
    let events = scheduleByHour[hour];
    if (options.officialOnly) {
      events = events.filter(e => e.source === 'database')
    }

    return events;
  }
  this.contentForHour = contentForHour;

  function hoursWithContent() {
    return Object.keys(scheduleByHour).filter(hour => {
      return contentForHour(hour).length > 0;
    }).sort();
  }
  this.hoursWithContent = hoursWithContent;

  function parseEvent(event) {
    event.start_date = new Date(Date.parse(event.start_date));
    event.end_date = new Date(Date.parse(event.end_date));

    return event;
  }

  rawSchedule.forEach(row => {
    let e = parseEvent(row);
    let startHour = `${e.start_date.toISOString().split(':')[0]}`

    if (scheduleByHour[startHour] === undefined) {
      scheduleByHour[startHour] = [];
    }
    scheduleByHour[startHour].push(e);
  });
}

function loadSchedule() {
  return fetch('/schedule/2018.json')
    .then(response => response.json())
    .then(rawSchedule => new Schedule(rawSchedule));
}

export default loadSchedule;

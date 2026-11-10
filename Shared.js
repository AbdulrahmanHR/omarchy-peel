.pragma library

var service = null
var listeners = []

function setService(instance) {
  service = instance
  var copy = listeners.slice()
  for (var i = 0; i < copy.length; i++) {
    try { copy[i](instance) } catch (e) {}
  }
}

function subscribe(fn) {
  if (listeners.indexOf(fn) === -1) listeners.push(fn)
  return service
}

function unsubscribe(fn) {
  var idx = listeners.indexOf(fn)
  if (idx !== -1) listeners.splice(idx, 1)
}

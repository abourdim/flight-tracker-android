/**
 * ✈️ Planes in the Sky — micro:bit Companion (MakeCode version)
 *
 * HOW TO USE:
 * 1. Go to makecode.microbit.org
 * 2. Create new project → switch to JavaScript mode
 * 3. Paste this code
 * 4. Add "bluetooth" extension (click Extensions → search "bluetooth")
 * 5. Download to micro:bit
 * 6. In the web app, tap the 🔌 button to pair
 *
 * BUTTONS:
 *   A = Cycle mode (Radar → Count → Compass → Flag)
 *   B = Cycle through planes (scroll callsign + distance)
 *   Shake = Request data refresh
 */

// === State ===
let displayMode = 0  // 0=radar, 1=count, 2=compass, 3=flag
let planeCount = 0
let selectedIdx = 0
let planes: { cs: string, d: number, b: number, a: number, c: string }[] = []
let nearest: { cs: string, d: number, b: number, a: number, c: string } | null = null
let alerting = false
let serialBuf = ""

// === Startup ===
basic.showString("SKY")
basic.showLeds(`
    . . # . .
    . # # # .
    # # # # #
    . # . # .
    . . . . .
`)
basic.pause(800)
basic.clearScreen()

// Enable Bluetooth UART
bluetooth.startUartService()

// === Button A: Cycle display mode ===
input.onButtonPressed(Button.A, function () {
    displayMode = (displayMode + 1) % 4
    let labels = ["RADAR", "COUNT", "POINT", "FLAG"]
    basic.showString(labels[displayMode])
    basic.pause(200)
})

// === Button B: Cycle through planes ===
input.onButtonPressed(Button.B, function () {
    if (planes.length > 0) {
        selectedIdx = (selectedIdx + 1) % planes.length
        let p = planes[selectedIdx]
        basic.showString(p.cs + " " + Math.round(p.d) + "km")
    } else {
        basic.showString("?")
    }
})

// === Shake: Request refresh ===
input.onGesture(Gesture.Shake, function () {
    bluetooth.uartWriteString("REFRESH\n")
    basic.showArrow(ArrowNames.North)
    basic.pause(200)
})

// === Bluetooth UART receive ===
bluetooth.onUartDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    let line = bluetooth.uartReadUntil(serial.delimiters(Delimiters.NewLine))
    parseMessage(line)
})

// Also support USB serial
serial.onDataReceived(serial.delimiters(Delimiters.NewLine), function () {
    let line = serial.readUntil(serial.delimiters(Delimiters.NewLine))
    parseMessage(line)
})

// === Parse incoming data ===
function parseMessage(msg: string) {
    msg = msg.trim()
    if (msg.length === 0) return

    let parts = msg.split("|")
    let cmd = parts[0]

    if (cmd === "U" && parts.length >= 2) {
        // Update: U|count|cs,d,b,a,c|cs,d,b,a,c|...
        planeCount = parseInt(parts[1]) || 0
        planes = []
        for (let i = 2; i < parts.length; i++) {
            let fields = parts[i].split(",")
            if (fields.length >= 5) {
                planes.push({
                    cs: fields[0],
                    d: parseFloat(fields[1]) || 0,
                    b: parseFloat(fields[2]) || 0,
                    a: parseFloat(fields[3]) || 0,
                    c: fields[4]
                })
            }
        }
        // Find nearest
        nearest = null
        let minD = 9999
        for (let p of planes) {
            if (p.d < minD) {
                minD = p.d
                nearest = p
            }
        }
    } else if (cmd === "A" && parts.length >= 5) {
        // Alert: A|cs|d|a|c
        overheadAlert({
            cs: parts[1],
            d: parseFloat(parts[2]) || 0,
            b: 0,
            a: parseFloat(parts[3]) || 0,
            c: parts[4]
        })
    } else if (cmd === "C") {
        planes = []
        planeCount = 0
        nearest = null
    }
}

// === Overhead alert animation ===
function overheadAlert(plane: { cs: string, d: number, b: number, a: number, c: string }) {
    alerting = true

    // Expanding ring
    basic.showLeds(`
        . . . . .
        . . . . .
        . . # . .
        . . . . .
        . . . . .
    `)
    basic.pause(80)
    basic.showLeds(`
        . . . . .
        . . # . .
        . # . # .
        . . # . .
        . . . . .
    `)
    basic.pause(80)
    basic.showLeds(`
        . . # . .
        . # . # .
        # . . . #
        . # . # .
        . . # . .
    `)
    basic.pause(80)

    // Plane icon
    basic.showLeds(`
        . . # . .
        . # # # .
        # # # # #
        . # . # .
        . . . . .
    `)
    music.play(music.tonePlayable(Note.C5, music.beat(BeatFraction.Quarter)), music.PlaybackMode.InBackground)
    basic.pause(100)
    music.play(music.tonePlayable(Note.E5, music.beat(BeatFraction.Quarter)), music.PlaybackMode.InBackground)
    basic.pause(100)
    music.play(music.tonePlayable(Note.G5, music.beat(BeatFraction.Half)), music.PlaybackMode.InBackground)
    basic.pause(400)

    // Scroll info
    basic.showString(plane.cs + " " + Math.round(plane.d) + "km")

    alerting = false
}

// === Radar display ===
function showRadar() {
    let img = images.createImage(`
        . . . . .
        . . . . .
        . . . . .
        . . . . .
        . . . . .
    `)
    // Center (you)
    img.setPixel(2, 2, true)

    let maxDist = 200
    for (let p of planes) {
        if (p.d > maxDist) continue
        let distNorm = Math.min(1, p.d / maxDist)
        let rad = p.b * Math.PI / 180
        let gx = Math.constrain(Math.round(2 + Math.sin(rad) * distNorm * 2.4), 0, 4)
        let gy = Math.constrain(Math.round(2 - Math.cos(rad) * distNorm * 2.4), 0, 4)
        if (gx === 2 && gy === 2) gy = 1
        img.setPixel(gx, gy, true)
    }
    img.showImage(0)
}

// === Compass pointer ===
function showCompass() {
    if (!nearest) {
        basic.showIcon(IconNames.Sad)
        return
    }
    let targetBearing = nearest.b
    let myHeading = input.compassHeading()
    let rel = ((targetBearing - myHeading) % 360 + 360) % 360

    let arrows = [
        ArrowNames.North, ArrowNames.NorthEast, ArrowNames.East, ArrowNames.SouthEast,
        ArrowNames.South, ArrowNames.SouthWest, ArrowNames.West, ArrowNames.NorthWest
    ]
    let idx = Math.floor((rel + 22.5) / 45) % 8
    basic.showArrow(arrows[idx])
}

// === Country flag ===
function showCountry() {
    if (!nearest) {
        basic.showString("?")
        return
    }
    // Show country code as scrolling text
    basic.showString(nearest.c || "?")
}

// === Main loop ===
basic.forever(function () {
    if (alerting) return

    if (displayMode === 0) {
        showRadar()
    } else if (displayMode === 1) {
        if (planeCount <= 9) {
            basic.showNumber(planeCount)
        } else {
            basic.showString("" + planeCount)
        }
    } else if (displayMode === 2) {
        showCompass()
    } else if (displayMode === 3) {
        showCountry()
    }

    basic.pause(200)
})

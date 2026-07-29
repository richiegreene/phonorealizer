# Phonorealizer

Inspired by Peter Ablinger's [_Phonorealism The Reproduction of "Phonographs" by Instruments_](https://ablinger.mur.at/phonorealism.html), this is a collection of analysis, composition, and performance tools to asist in spectral phonorealism (including hyperrealism, pseudorealism, surrealism, etc).

## Modifier

The modifier area of this tool box is designed to expand off of Michael Klingbeil’s _Sinusoidal Partial Editing Analysis and Resynthesis [SPEAR](https://www.klingbeil.com/spear/)_. It contains all transormation procedures there and adds to them to allow the composer to more intuitively modify the rendered spectrum.

<table>
  <tr>
    <td width="50%">
      <div align="center">
        <img
          src="https://github.com/user-attachments/assets/f7977eef-3751-4838-bb51-82a6483e139e"
          width="500"
        />
      </div>
      <sub>
        Original excerpt from Anne Briggs,
        <em>“Lowlands,”</em> <em>The Hazards of Love</em>, 1964.
        <br /><br /><br />
      </sub>
    </td>
    <td width="50%">
      <div align="center">
        <img
          src="https://github.com/user-attachments/assets/1fbebe67-ab4f-4018-8dd5-e219edf18ae7"
          width="500"
        />
      </div>
      <sub>
        <strong>A:</strong> isolated 8th partial, susceptible to individual transformation<br />
        <strong>B:</strong> partials snapped to a 4:5:6 just major chord (spectral vocoder)<br />
        <strong>C:</strong> partials snapped to nearest 12-EDO approximation<br />
        <strong>D:</strong> partials flattened in harmonic contours via smoothstep function.
      </sub>
    </td>
  </tr>
</table>


## Performer

[`phonorealism_web`](phonorealism_web) is a browser-based in-ear monitoring system for ensembles playing this material. Designed for phone interfaces, it separates _Performers_ from a _Conductor_, where the conductor loads the score and starts playback for all players simultaneously.

Each performer claims a part and gets their line re-synthesised into their earbuds — balanced against the rest of the ensemble — alongside a scrolling display comparing their live pitch and amplitude against what is written. It reads justidraw `.sav` files directly as well as the CSV exported here.

Nothing is streamed between devices: the hub distributes the score and a single timestamp for the downbeat, and every device plays from its own clock thereafter. Sync accuracy is measured per device and shown live, so a bad network is visible before the downbeat rather than after it. See the [project README](phonorealism_web/README.md) for setup.
<table>
  <tr>
    <td width="100%">
      <div align="center">
        <img
          src="https://github.com/user-attachments/assets/8f65429d-cc4a-4962-a5f5-9827635c3b72"
        />
      </div>
      <sub>
        Scrolling “karaoke-style” display parts, where upper portion of screen depicts pitch and lower portion depicts amplitude.<br />
        <strong>A:</strong> depicts real-time performer<br />
        <strong>B:</strong> depicts desired/written musical material<br />
      </sub>
    </td>
  </tr>
</table>

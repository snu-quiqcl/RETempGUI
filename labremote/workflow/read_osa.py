"""Connect the device in its tab before running this workflow."""


def main(devices):
    osa = devices.osa('aq6373')
    spectrum = osa.read_spectrum().wait()
    print('OSA points:', len(spectrum['frequency_thz']))

__all__ = ["CalibrationWizard"]


def __getattr__(name):
    if name != "CalibrationWizard":
        raise AttributeError(name)
    from coc_bot.calibration.wizard import CalibrationWizard
    return CalibrationWizard

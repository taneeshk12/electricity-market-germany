Attribute VB_Name = "RiskDashboard"
' =============================================================================
' Power Price Risk Workbook: one-click dashboard refresh.
'
' RefreshDashboard (assigned to the button on the Dashboard sheet):
'   1. imports prices_daily.csv from the workbook's folder into tblDaily
'      (written by `python -m risk_workbook.export`; skipped if the file is absent),
'   2. refills the formula columns and resizes the d_* names and the charts,
'   3. rebuilds the pivot tables and pivot charts,
'   4. recalculates everything (including the Data Tables) and stamps the time.
'
' Works in Excel for Windows and Excel for Mac (2016+). The CSV is parsed by hand
' with Val(), which always reads "." as the decimal separator, so the import does
' not depend on the regional settings of the machine.
' =============================================================================
Option Explicit

Private Const CSV_NAME As String = "prices_daily.csv"
Private Const CSV_HEADER As String = "date,year,month,weekday,day_type,base_price,peak_price,min_price,max_price,negative_hours,load_gwh,renewable_share"
Private Const DATA_SHEET As String = "Data"
Private Const DASH_SHEET As String = "Dashboard"
Private Const PIVOT_SHEET As String = "Pivots"
Private Const TABLE_NAME As String = "tblDaily"
Private Const RAW_COLS As Long = 12
Private Const PIVOT_CHART_PREFIX As String = "pc_"

Public Sub RefreshDashboard()
    Dim lo As ListObject, oldLast As Long, newLast As Long, imported As Long
    Dim calcMode As XlCalculation

    calcMode = Application.Calculation
    Application.ScreenUpdating = False
    Application.Calculation = xlCalculationManual
    On Error GoTo Fail

    Set lo = ThisWorkbook.Worksheets(DATA_SHEET).ListObjects(TABLE_NAME)
    oldLast = LastRow(lo)
    imported = ImportCsv(lo)
    newLast = LastRow(lo)

    ResizeNames lo
    If newLast <> oldLast Then UpdateChartRanges oldLast, newLast
    BuildPivots lo

    Application.Calculation = xlCalculationAutomatic
    Application.CalculateFull
    ThisWorkbook.Names("LastRefresh").RefersToRange.Value = Now
    Application.Calculation = calcMode
    Application.ScreenUpdating = True

    If imported > 0 Then
        MsgBox "Imported " & imported & " days from " & CSV_NAME & " and refreshed the dashboard.", vbInformation
    Else
        MsgBox "No " & CSV_NAME & " next to the workbook: recalculated and rebuilt pivots on the existing data.", _
               vbInformation
    End If
    Exit Sub

Fail:
    Application.Calculation = calcMode
    Application.ScreenUpdating = True
    MsgBox "Refresh failed: " & Err.Description, vbExclamation
End Sub

' Rebuild pivots and charts without importing (e.g. after first opening the .xlsx).
Public Sub BuildDashboard()
    BuildPivots ThisWorkbook.Worksheets(DATA_SHEET).ListObjects(TABLE_NAME)
    Application.CalculateFull
End Sub

' One-time setup: put a Refresh button on the Dashboard.
Public Sub AddRefreshButton()
    Dim ws As Worksheet, shp As Shape
    Set ws = ThisWorkbook.Worksheets(DASH_SHEET)
    On Error Resume Next
    ws.Shapes("btnRefresh").Delete
    On Error GoTo 0
    Set shp = ws.Shapes.AddShape(5, ws.Range("J4").Left, ws.Range("J4").Top, 150, 36) ' 5 = rounded rectangle
    shp.Name = "btnRefresh"
    shp.Fill.ForeColor.RGB = RGB(31, 56, 100)
    shp.Line.Visible = msoFalse
    With shp.TextFrame2.TextRange
        .Text = "Refresh Dashboard"
        .Font.Bold = msoTrue
        .Font.Size = 12
        .Font.Fill.ForeColor.RGB = RGB(255, 255, 255)
    End With
    shp.TextFrame2.VerticalAnchor = msoAnchorMiddle
    shp.TextFrame2.TextRange.ParagraphFormat.Alignment = msoAlignCenter
    shp.OnAction = "RefreshDashboard"
End Sub

' --- Import ---------------------------------------------------------------------

Private Function ImportCsv(lo As ListObject) As Long
    Dim path As String, text As String, lines() As String, f As Integer
    Dim n As Long, i As Long, j As Long, fields() As String, data() As Variant, keep As Long

    path = ThisWorkbook.Path & Application.PathSeparator & CSV_NAME
    If Len(Dir(path)) = 0 Then Exit Function

    f = FreeFile
    Open path For Binary Access Read As #f
    text = Space$(LOF(f))
    Get #f, , text
    Close #f

    ' Accept LF or CRLF line endings.
    lines = Split(Replace(text, vbCr, ""), vbLf)
    If Trim$(lines(0)) <> CSV_HEADER Then Err.Raise vbObjectError + 1, , "Unexpected CSV header in " & CSV_NAME

    For i = 1 To UBound(lines)
        If Len(lines(i)) > 0 Then n = n + 1
    Next i
    If n = 0 Then Err.Raise vbObjectError + 2, , CSV_NAME & " has no data rows"

    ReDim data(1 To n, 1 To RAW_COLS)
    j = 0
    For i = 1 To UBound(lines)
        If Len(lines(i)) > 0 Then
            j = j + 1
            fields = Split(lines(i), ",")
            If UBound(fields) + 1 <> RAW_COLS Then Err.Raise vbObjectError + 3, , "Bad CSV line " & (i + 1)
            data(j, 1) = DateSerial(CInt(Left$(fields(0), 4)), CInt(Mid$(fields(0), 6, 2)), CInt(Mid$(fields(0), 9, 2)))
            data(j, 2) = CLng(Val(fields(1)))
            data(j, 3) = CLng(Val(fields(2)))
            data(j, 4) = fields(3)
            data(j, 5) = fields(4)
            data(j, 6) = Num(fields(5))
            data(j, 7) = Num(fields(6))
            data(j, 8) = Num(fields(7))
            data(j, 9) = Num(fields(8))
            data(j, 10) = Num(fields(9))
            data(j, 11) = Num(fields(10))
            data(j, 12) = Num(fields(11))
        End If
    Next i

    ' Shrink first if the new export is shorter, then resize the table to n data rows.
    keep = lo.ListRows.Count
    If keep > n Then lo.DataBodyRange.Offset(n).Resize(keep - n).Rows.Delete
    lo.Resize lo.Range.Resize(n + 1, lo.ListColumns.Count)

    lo.DataBodyRange.Cells(1, 1).Resize(n, RAW_COLS).Value = data
    lo.ListColumns(1).DataBodyRange.NumberFormat = "yyyy-mm-dd"

    ' Copy each formula column's first-row formula down the whole column.
    For j = RAW_COLS + 1 To lo.ListColumns.Count
        With lo.ListColumns(j).DataBodyRange
            .FormulaR1C1 = .Cells(1, 1).FormulaR1C1
        End With
    Next j
    ImportCsv = n
End Function

Private Function Num(ByVal s As String) As Variant
    If Len(Trim$(s)) = 0 Then
        Num = Empty
    Else
        Num = Val(s)
    End If
End Function

Private Function LastRow(lo As ListObject) As Long
    LastRow = lo.Range.Row + lo.Range.Rows.Count - 1
End Function

' --- Names and charts -----------------------------------------------------------

Private Sub ResizeNames(lo As ListObject)
    Dim names As Variant, cols As Variant, i As Long
    names = Array("d_Date", "d_Year", "d_Month", "d_Base", "d_NegHours", "d_Change", "d_PnL", _
                  "d_RollVol", "d_HistVaR", "d_ParamVaR", "d_HistBreach", "d_ParamBreach")
    cols = Array("Date", "Year", "Month", "BasePrice", "NegHours", "Change", "BuyerPnL", _
                 "RollVol", "HistVaR", "ParamVaR", "HistBreach", "ParamBreach")
    For i = LBound(names) To UBound(names)
        ThisWorkbook.Names(names(i)).RefersTo = "='" & DATA_SHEET & "'!" & _
            lo.ListColumns(cols(i)).DataBodyRange.Address
    Next i
End Sub

' Charts built in Python point at fixed Data rows; move their last row to the new one.
Private Sub UpdateChartRanges(ByVal oldLast As Long, ByVal newLast As Long)
    Dim ws As Worksheet, co As ChartObject, s As Series, f As String
    For Each ws In ThisWorkbook.Worksheets
        For Each co In ws.ChartObjects
            If Not IsPivotChart(co) Then
                For Each s In co.Chart.SeriesCollection
                    f = s.Formula
                    If InStr(f, DATA_SHEET & "'!") > 0 Or InStr(f, DATA_SHEET & "!") > 0 Then
                        f = Replace(f, "$" & oldLast & ",", "$" & newLast & ",")
                        f = Replace(f, "$" & oldLast & ")", "$" & newLast & ")")
                        s.Formula = f
                    End If
                Next s
            End If
        Next co
    Next ws
End Sub

Private Function IsPivotChart(co As ChartObject) As Boolean
    Dim pt As PivotTable
    On Error Resume Next
    Set pt = co.Chart.PivotLayout.PivotTable
    IsPivotChart = Not pt Is Nothing
    On Error GoTo 0
End Function

' --- Pivot tables and pivot charts ---------------------------------------------

Private Sub BuildPivots(lo As ListObject)
    Dim wsP As Worksheet, wsD As Worksheet, pc As PivotCache, co As ChartObject, i As Long
    Set wsD = ThisWorkbook.Worksheets(DASH_SHEET)

    ' Remove old pivot charts and the old pivot sheet, then rebuild from the current table.
    For i = wsD.ChartObjects.Count To 1 Step -1
        If Left$(wsD.ChartObjects(i).Name, Len(PIVOT_CHART_PREFIX)) = PIVOT_CHART_PREFIX Then wsD.ChartObjects(i).Delete
    Next i
    Application.DisplayAlerts = False
    On Error Resume Next
    ThisWorkbook.Worksheets(PIVOT_SHEET).Delete
    On Error GoTo 0
    Application.DisplayAlerts = True

    Set wsP = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
    wsP.Name = PIVOT_SHEET
    wsP.Range("A1").Value = "Pivot tables on tblDaily (rebuilt by RefreshDashboard; do not edit)"
    wsP.Range("A1").Font.Bold = True

    Set pc = ThisWorkbook.PivotCaches.Create(SourceType:=xlDatabase, SourceData:=TABLE_NAME)

    AddPivot pc, wsP.Range("A3"), "ptMonthlyPrice", "Month", "Year", "BasePrice", xlAverage, "Avg base price", "0.0"
    AddPivot pc, wsP.Range("A20"), "ptNegHours", "Month", "Year", "NegHours", xlSum, "Negative hours", "0"
    AddPivot pc, wsP.Range("A37"), "ptBreaches", "Year", "", "HistBreach", xlSum, "Hist. VaR breaches", "0"
    With wsP.PivotTables("ptBreaches").AddDataField(wsP.PivotTables("ptBreaches").PivotFields("ParamBreach"), _
                                                   "Param. VaR breaches", xlSum)
        .NumberFormat = "0"
    End With

    AddPivotChart wsD, wsP.PivotTables("ptMonthlyPrice"), "pc_MonthlyPrice", xlLine, _
                  "Average base price by month and year (EUR/MWh)", "A30"
    AddPivotChart wsD, wsP.PivotTables("ptNegHours"), "pc_NegHours", xlColumnClustered, _
                  "Negative-price hours by month and year", "J30"
    AddPivotChart wsD, wsP.PivotTables("ptBreaches"), "pc_Breaches", xlColumnClustered, _
                  "VaR breaches by year (historical vs. parametric)", "A48"
End Sub

Private Sub AddPivot(pc As PivotCache, dest As Range, ByVal ptName As String, ByVal rowField As String, _
                     ByVal colField As String, ByVal dataField As String, ByVal fn As XlConsolidationFunction, _
                     ByVal caption As String, ByVal fmt As String)
    Dim pt As PivotTable
    Set pt = pc.CreatePivotTable(TableDestination:=dest, TableName:=ptName)
    pt.PivotFields(rowField).Orientation = xlRowField
    If Len(colField) > 0 Then pt.PivotFields(colField).Orientation = xlColumnField
    With pt.AddDataField(pt.PivotFields(dataField), caption, fn)
        .NumberFormat = fmt
    End With
    pt.RowAxisLayout xlTabularRow
End Sub

Private Sub AddPivotChart(ws As Worksheet, pt As PivotTable, ByVal chartName As String, ByVal chartType As XlChartType, _
                          ByVal title As String, ByVal anchor As String)
    Dim co As ChartObject
    Set co = ws.ChartObjects.Add(ws.Range(anchor).Left, ws.Range(anchor).Top, 450, 260)
    co.Name = chartName
    With co.Chart
        .SetSourceData pt.TableRange1
        .ChartType = chartType
        .HasTitle = True
        .ChartTitle.Text = title
    End With
End Sub
